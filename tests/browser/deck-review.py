"""Exercise the real rendered-slide diff using the built example deck."""

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from site_server import _serve

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "plugins/asta-tools/skills/workspace/assets"
spec = importlib.util.spec_from_file_location("changed", ASSETS / "what-changed.py")
changed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changed)


def check(site, artifacts):
    artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        # A published preview already carries its own What changed output, which
        # would otherwise be diffed as extra pages beside the deck under test.
        generated = shutil.ignore_patterns(
            "demo", "what-changed.html", "what-changed-decks", "what-changed-assets"
        )
        for side in ("old", "new"):
            shutil.copytree(site, root / side, ignore=generated)
        deck = Path("slides/attention/slides.html")
        original = (root / "old" / deck).read_text()
        slides = changed.reveal_slides(original)
        assert len(slides) >= 5
        # Root-relative images resolve at each site origin, including lazy-loaded images.
        image = '<img data-src="/review-image.svg" alt="Review image" width="300" height="100">'
        baseline = original.replace(slides[2]["body"], slides[2]["body"] + image, 1)
        after = baseline.replace(
            slides[1]["body"], slides[1]["body"].replace("</h", " revised</h", 1), 1
        )
        after = after.replace(
            slides[-1]["body"], "<h2>A new slide</h2><p>New content.</p>", 1
        )
        # A new id makes this an addition/removal, rather than an edit.
        after = after.replace('id="' + slides[-1]["id"] + '"', 'id="review-added"', 1)
        for side, document, color in [
            ("old", baseline, "#105257"),
            ("new", after, "#ffa31c"),
        ]:
            (root / side / deck).write_text(document)
            (root / side / "review-image.svg").write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100"><rect width="300" height="100" fill="{color}"/></svg>'
            )
        out = root / "new/what-changed.html"
        result = subprocess.run(
            [
                sys.executable,
                str(ASSETS / "what-changed.py"),
                "--old",
                str(root / "old"),
                "--new",
                str(root / "new"),
                "--out",
                str(out),
                "--render-decks",
                str(root / "new/what-changed-decks"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "slides as text" not in result.stderr, result.stderr
        server = _serve(str(root / "new"))
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(
                    f"http://127.0.0.1:{server.server_address[1]}/what-changed.html"
                )
                page.locator(".deck-review").wait_for()
                assert page.locator(".dr-changed").count() > 0
                assert page.locator(".dr-look").count() > 0
                assert page.locator(".dr-new").count() > 0
                assert page.locator(".dr-removed").count() == 1
                assert page.locator("details.dr-unchanged").count() > 0
                # Each view hides the other views' frames (display: none), which
                # never become stable, so only the shown frames are waited on.
                for view in ["before", "clean", "marked"]:
                    page.locator(f'.dr-seg button[data-v="{view}"]').click()
                    frames = page.locator(".dr-slide iframe:visible").all()
                    assert frames, view
                    for frame in frames:
                        frame.scroll_into_view_if_needed()
                        page.wait_for_function(
                            "f => !!f.contentWindow.Reveal && f.contentWindow.Reveal.isReady()",
                            arg=frame.element_handle(),
                        )
                assert (
                    page.locator("iframe")
                    .first.content_frame.locator(".reveal")
                    .count()
                    == 1
                )
                page.screenshot(path=str(artifacts / "deck-review-live.png"))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
