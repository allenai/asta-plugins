"""Exercise the real rendered-slide diff using the built example deck."""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "plugins/asta-tools/skills/workspace/assets"
spec = importlib.util.spec_from_file_location("changed", ASSETS / "what-changed.py")
changed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changed)
spec = importlib.util.spec_from_file_location("review", ASSETS / "deck-review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def check(site, artifacts):
    artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for side in ("old", "new"):
            shutil.copytree(site, root / side)
        deck = Path("slides/attention/slides.html")
        original = (root / "old" / deck).read_text()
        slides = changed.reveal_slides(original)
        assert len(slides) >= 5
        image = (
            '<img src="review-image.svg" alt="Review image" width="300" height="100">'
        )
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
            (root / side / deck.parent / "review-image.svg").write_text(
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
        server = review._serve(str(root / "new"))
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(
                    f"http://127.0.0.1:{server.server_address[1]}/what-changed.html"
                )
                page.locator(".deck-review").wait_for()
                data = json.loads(page.locator(".dr-data").inner_text())
                kinds = [item["kind"] for item in data["items"]]
                assert "changed" in kinds and "look" in kinds and "new" in kinds, kinds
                assert len(data["removed"]) == 1, data
                assert page.locator(".dr-more").count() > 0
                page.locator(".deck-review").scroll_into_view_if_needed()
                page.screenshot(path=str(artifacts / "deck-review-marked.png"))
                page.get_by_role("button", name="Clean", exact=True).click()
                assert (
                    page.locator('.dr-seg button[data-v="clean"]').get_attribute(
                        "aria-pressed"
                    )
                    == "true"
                )
                page.screenshot(path=str(artifacts / "deck-review-clean.png"))
                page.get_by_role("button", name="Before / after", exact=True).click()
                assert page.locator(".dr-pair:visible").count() >= 2
                page.screenshot(path=str(artifacts / "deck-review-before-after.png"))
                for image in page.locator(".dr-slide:visible img:visible").all():
                    image.scroll_into_view_if_needed()
                    image.wait_for(state="visible")
                    assert image.evaluate(
                        "(i) => i.complete && i.naturalWidth === 1600"
                    ), image.get_attribute("src")
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
