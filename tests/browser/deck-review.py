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


def capture_regressions(root, deck, original):
    """A count-only edit must leave other slides unchanged, including vertical stacks."""
    before = root / "old" / deck
    after = root / "new" / deck
    before.write_text(original)
    addition = (
        '<section id="review-extra"><h2>Extra slide</h2><p>Only addition.</p></section>'
    )
    added = original.replace(
        '<div class="slides">', '<div class="slides">' + addition, 1
    )
    assert added != original
    after.write_text(added)
    for old_doc, new_doc, expected in [
        (original, added, "new"),
        (added, original, "removed"),
    ]:
        before.write_text(old_doc)
        after.write_text(new_doc)
        old, new = changed.reveal_slides(old_doc), changed.reveal_slides(new_doc)
        renderer = review.Renderer(root / "old", root / "new")
        try:
            rendered = review.review(
                str(deck),
                str(deck),
                str(root / "regression-images"),
                "images",
                old,
                new,
                changed.match_slides(old, new),
                renderer,
            )
            data = json.loads(
                rendered.split('class="dr-data">', 1)[1].split("</script>", 1)[0]
            )
            kinds = [item["kind"] for item in data["items"]]
            assert not {"look", "changed"}.intersection(kinds), kinds
            assert kinds.count("new") == (1 if expected == "new" else 0), kinds
            assert len(data["removed"]) == (1 if expected == "removed" else 0), data
        finally:
            renderer.close()
    # The same text filter feeds matching and marks, and preserves SVG/MathML.
    old_extra = '<aside class="notes">Old private note</aside><svg width="80" height="40"><text y="20">Graph</text></svg><math><mi>x</mi></math>'
    new_extra = old_extra.replace("Old private note", "New private note")
    slides = changed.reveal_slides(original)
    before.write_text(
        original.replace(slides[2]["body"], slides[2]["body"] + old_extra, 1)
    )
    after.write_text(
        original.replace(slides[2]["body"], slides[2]["body"] + new_extra, 1)
    )
    renderer = review.Renderer(root / "old", root / "new")
    try:
        old, new = (
            changed.reveal_slides(before.read_text()),
            changed.reveal_slides(after.read_text()),
        )
        assert (
            review.review(
                str(deck),
                str(deck),
                str(root / "regression-images"),
                "images",
                old,
                new,
                changed.match_slides(old, new),
                renderer,
            )
            is None
        )
        page = renderer.page("new", str(deck))
        page.evaluate(review.GOTO_JS, 2)
        tokens = page.evaluate(review.LIST_JS)[2]
        assert "private note" not in tokens and "Graph" not in tokens
        page.evaluate(review.MARK_WORDS_JS, [review.MARK_CSS, ["different"]])
        assert (
            page.locator(
                "svg ins, svg del, math ins, math del, .notes ins, .notes del"
            ).count()
            == 0
        )
        assert page.locator("svg text").text_content() == "Graph"
    finally:
        renderer.close()


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
        capture_regressions(root, deck, original)
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
                assert len(data["items"]) == len(slides), (
                    "Every unchanged run is inspectable"
                )
                assert page.locator(".dr-more").count() > 0
                page.locator(".deck-review").scroll_into_view_if_needed()
                page.evaluate("""async () => {
                  await Promise.all([...document.querySelectorAll('.dr-slide img')].map(i => {
                    i.loading = 'eager'; return i.decode().catch(() => {});
                  }));
                }""")
                page.screenshot(path=str(artifacts / "deck-review-marked.png"))
                page.get_by_role("button", name="Clean", exact=True).click()
                assert (
                    page.locator('.dr-seg button[data-v="clean"]').get_attribute(
                        "aria-pressed"
                    )
                    == "true"
                )
                page.evaluate("""async () => {
                  await Promise.all([...document.querySelectorAll('.dr-slide img')].map(i => {
                    i.loading = 'eager'; return i.decode().catch(() => {});
                  }));
                }""")
                page.screenshot(path=str(artifacts / "deck-review-clean.png"))
                page.get_by_role("button", name="Before / after", exact=True).click()
                assert page.locator(".dr-pair:visible").count() >= 2
                page.evaluate("""async () => {
                  await Promise.all([...document.querySelectorAll('.dr-slide img')].map(i => {
                    i.loading = 'eager'; return i.decode().catch(() => {});
                  }));
                }""")
                page.screenshot(path=str(artifacts / "deck-review-before-after.png"))
                for image in page.locator(".dr-slide:visible img:visible").all():
                    image.scroll_into_view_if_needed()
                    image.wait_for(state="visible")
                    assert image.evaluate(
                        "(i) => i.complete && i.naturalWidth === 1600"
                    ), image.get_attribute("src")
                for button in page.locator(".dr-more").all():
                    button.click()
                assert page.locator(".dr-unchanged:visible").count() == kinds.count(
                    "unchanged"
                )
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
