"""Run the local `make what-changed` on an edit to the example deck; its slides must render."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "review", ROOT / "plugins/asta-tools/skills/workspace/assets/deck-review.py"
)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def check(project, artifacts):
    artifacts.mkdir(parents=True, exist_ok=True)
    deck = project / "slides/attention/slides.qmd"
    original = deck.read_text()
    edited = original.replace(
        "## Keep the talk beside its sources\n",
        "## Keep the talk beside its sources and data\n",
        1,
    ).replace(
        "# The workspace\n",
        "# The workspace\n\n## A slide added locally\n\nReviewed before any PR.\n",
        1,
    )
    assert edited.count("locally") == 1 and "sources and data" in edited
    deck.write_text(edited)
    try:
        result = subprocess.run(
            [
                "make",
                "what-changed",
                f"PYTHON={sys.executable}",
                "WHAT_CHANGED_BASE=HEAD",
            ],
            cwd=project,
            capture_output=True,
            text=True,
        )
    finally:
        deck.write_text(original)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "slides as text" not in result.stderr, result.stderr
    site = project / "_site"
    assert 'class="deck-review"' in (site / "what-changed.html").read_text()
    assert list((site / "what-changed-assets/what-changed-decks").rglob("*.png"))
    server = review._serve(str(site))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/what-changed.html")
            page.locator(".deck-review").wait_for()
            data = json.loads(page.locator(".dr-data").text_content())
            kinds = [item["kind"] for item in data["items"]]
            assert kinds.count("new") == 1 and "changed" in kinds, kinds
            assert "look" not in kinds and not data["removed"], data
            # Served from the preview's _site, as the local page is.
            for image in page.locator(".dr-slide:visible img:visible").all():
                image.scroll_into_view_if_needed()
                assert image.evaluate(
                    "(i) => new Promise(r => i.complete ? r() : i.addEventListener('load', r, {once: true}))"
                    ".then(() => i.naturalWidth === 1600)"
                ), image.get_attribute("src")
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


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
