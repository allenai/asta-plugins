"""Run the local `asta workspace what-changed` on an edit to the example deck; its slides must render."""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "review", ROOT / "plugins/asta-tools/skills/workspace/assets/deck-review.py"
)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
# Display shots are taken at device scale, so slide images are this wide.
DISPLAY_WIDTH = review.VIEWPORT["width"] * review.DISPLAY_SCALE


def deploy_preview(site):
    """Run the shared workflow's PR-preview noindex step over a built site."""
    lines = (
        (ROOT / ".github/workflows/workspace-quarto-site.yml").read_text().splitlines()
    )
    start = next(
        i
        for i, line in enumerate(lines)
        if 'find "$tmp/pr-preview/pr-$PR_NUMBER"' in line
    )
    injection = "\n".join(line.strip() for line in lines[start : start + 2])
    with tempfile.TemporaryDirectory() as tmp:
        preview = Path(tmp, "pr-preview/pr-1")
        shutil.copytree(site, preview, symlinks=True)
        result = subprocess.run(
            ["bash", "-eu", "-o", "pipefail", "-c", injection],
            env={"PATH": os.environ["PATH"], "tmp": tmp, "PR_NUMBER": "1"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "noindex" in (preview / "what-changed.html").read_text()


def deploy_main(site):
    """Exercise the shared main publication script with the deck comparison."""
    workflow = (ROOT / ".github/workflows/workspace-quarto-site.yml").read_text()
    begin = workflow.index("# BEGIN main publication")
    end = workflow.index("# END main publication", begin)
    script = workflow[begin:end]
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp, "workspace")
        shutil.copytree(site, workspace / "_site", symlinks=True)
        published = Path(tmp, "published")
        preview = published / "pr-preview/pr-1/index.html"
        preview.parent.mkdir(parents=True)
        preview.write_text("keep existing preview")
        (published / "stale.html").write_text("remove old main page")
        result = subprocess.run(
            ["bash", "-eu", "-o", "pipefail", "-c", script],
            env={
                "PATH": os.environ["PATH"],
                "GITHUB_WORKSPACE": str(workspace),
                "tmp": str(published),
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert preview.read_text() == "keep existing preview"
        assert not (published / "stale.html").exists()
        assert (
            'class="deck-live deck-review"'
            in (published / "what-changed.html").read_text()
        )
        images = [p for p in site.glob("what-changed-decks/**/*.html") if p.is_file()]
        assert images
        for image in images:
            assert (
                published / image.relative_to(site)
            ).read_bytes() == image.read_bytes()
        assert "noindex" not in (published / "what-changed.html").read_text()
    print("Validated shared main publication with live marked decks")


def check(project, artifacts):
    artifacts.mkdir(parents=True, exist_ok=True)
    deck = project / "slides/attention/slides.qmd"
    original = deck.read_text()
    edited = (
        original.replace(
            "## Keep the talk beside its sources\n",
            "## Keep the talk beside its sources and data\n",
            1,
        )
        .replace(
            # Replace words, not only add them, so Changes marked has struck words too.
            "Write the talk, review and paper in the same repository.\n",
            "Write the talk, review and paper in one repository.\n",
            1,
        )
        .replace(
            "# The workspace\n",
            "# The workspace\n\n## A slide added locally\n\nReviewed before any PR.\n",
            1,
        )
    )
    assert edited.count("locally") == 1 and "sources and data" in edited
    assert "paper in one repository" in edited
    deck.write_text(edited)
    try:
        result = subprocess.run(
            [
                "asta",
                "workspace",
                "what-changed",
                "HEAD",
            ],
            cwd=project,
            capture_output=True,
            text=True,
        )
    finally:
        deck.write_text(original)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "slides as text" not in result.stderr, result.stderr
    site = project / ".asta/cache/what-changed"
    assert 'class="deck-live deck-review"' in (site / "what-changed.html").read_text()
    images = site / "what-changed-decks"
    assert list(images.rglob("*.html"))
    # A folder named *.html is handed to the deploy's noindex sed as a file.
    assert not [p for p in images.rglob("*.html") if p.is_dir()]
    deploy_preview(site)
    deploy_main(site)
    server = review._serve(str(site))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/what-changed.html")
            page.locator(".deck-review").wait_for()
            assert page.locator(".dr-changed").count() > 0
            assert page.locator(".dr-new").count() == 1
            # Only the edited and added slides are shown; the rest fold away.
            assert page.locator(".dr-look").count() == 0
            assert page.locator("details.dr-unchanged").count() > 0
            for view in ("marked", "clean", "before"):
                live = page.locator(".deck-live").first
                live.locator(f'.dr-seg button[data-v="{view}"]').click()
                frames = live.locator(".dr-slide iframe:visible").all()
                assert frames, view
                marked_seen = set()
                for frame in frames:
                    frame.scroll_into_view_if_needed()
                    page.wait_for_function(
                        "f => !!f.contentWindow.Reveal && f.contentWindow.Reveal.isReady()",
                        arg=frame.element_handle(),
                    )
                    child = frame.element_handle().content_frame()
                    assert child is not None
                    # Exercise the narrow frame that activates Reveal's scroll view
                    # by default, and verify identity rather than numeric position.
                    frame.evaluate(
                        "f => { f.style.width = '378px'; f.style.height = '212px'; }"
                    )
                    child.wait_for_function(
                        "id => !Reveal.isScrollView() && Reveal.getCurrentSlide().id === id",
                        arg=frame.get_attribute("data-dr-slide-id"),
                    )
                    # The current slide must sit inside the frame, not below it.
                    box = child.evaluate(
                        "() => { const r = Reveal.getCurrentSlide()"
                        ".getBoundingClientRect(); return [r.top, r.bottom, r.height,"
                        " innerHeight]; }"
                    )
                    top, bottom, height, viewport = box
                    assert height > 0 and top >= -1 and bottom <= viewport + 1, box
                    # A frame stays on its slide: keys don't navigate, builds all show.
                    child.press("body", "ArrowRight")
                    assert child.evaluate(
                        "() => Reveal.getCurrentSlide().id"
                    ) == frame.get_attribute("data-dr-slide-id")
                    assert child.evaluate(
                        "() => [...Reveal.getCurrentSlide().querySelectorAll('.fragment')]"
                        ".every(f => getComputedStyle(f).opacity === '1')"
                    )
                    if view == "marked":
                        marked_seen.update(
                            child.evaluate(
                                "() => [...Reveal.getCurrentSlide()"
                                ".querySelectorAll('.dr-live')].map(e => e.tagName)"
                            )
                        )
                if view == "marked":
                    # Removed words struck and added words marked, on the one slide.
                    assert {"INS", "DEL"} <= marked_seen, marked_seen
            # The page borrows the site's theme, as the PR preview does.
            assert page.evaluate(
                "() => [...document.styleSheets].some("
                "s => s.href && s.href.includes('site_libs') && s.cssRules.length)"
            ), "the site's theme did not load"
            page.locator(".deck-review").scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / "local-what-changed-deck.png"))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


THEMED_JS = (
    "() => ['bootstrap', 'asta-theme'].every(name => [...document.styleSheets]"
    ".some(s => s.href && s.href.includes(name) && s.cssRules.length))"
    ' && !/^"?times/i.test(getComputedStyle(document.body).fontFamily)'
)


def check_themed_without_preview(project, artifacts, redirect_preview=False):
    """A slide-only edit with no themed preview must still read like the site.

    With redirect_preview, the running preview is a partial one whose home page
    is only Quarto's redirect, so it carries no stylesheets to borrow.
    """
    deck = project / "slides/attention/slides.qmd"
    original = deck.read_text()
    preview = project / "_site"
    parked = project.with_name(project.name + "-site-parked")
    preview.rename(parked)
    if redirect_preview:
        preview.mkdir()
        (preview / "index.html").write_text(
            "<html><head><title>Redirect to slides/attention/slides.html</title>"
            '<meta http-equiv="refresh" content="0;url=slides/attention/slides.html">'
            "</head></html>"
        )
    edited = original.replace(
        "## Keep the talk beside its sources\n",
        "## Keep the talk beside its sources and data\n",
        1,
    )
    assert edited != original
    deck.write_text(edited)
    try:
        result = subprocess.run(
            ["asta", "workspace", "what-changed", "HEAD"],
            cwd=project,
            capture_output=True,
            text=True,
        )
    finally:
        deck.write_text(original)
        shutil.rmtree(preview, ignore_errors=True)
        parked.rename(preview)
    assert result.returncode == 0, result.stdout + result.stderr
    site = project / ".asta/cache/what-changed"
    assert (site / "site_libs/bootstrap").is_dir(), "snapshot has no site theme"
    server = review._serve(str(site))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/what-changed.html")
            page.locator(".deck-review").wait_for()
            assert page.evaluate(THEMED_JS), "What changed page is unstyled"
            # The home page rendered for the theme is not itself compared.
            assert "Redirect" not in page.content(), "home page reported as changed"
            name = "redirect-preview" if redirect_preview else "no-preview"
            page.screenshot(path=str(artifacts / f"local-what-changed-{name}.png"))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    for redirect_preview in (False, True):
        check_themed_without_preview(
            Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), redirect_preview
        )
