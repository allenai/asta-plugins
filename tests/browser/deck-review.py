"""Exercise the real rendered-slide diff using the built example deck."""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
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
# Display shots are taken at device scale, so slide images are this wide.
DISPLAY_WIDTH = review.VIEWPORT["width"] * review.DISPLAY_SCALE


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
        assert page.evaluate("() => Reveal.getConfig().autoSlide") == 0
        # Display shots draw the deck's own slide number back; comparison shots never do.
        plain = renderer.shoot("new", str(deck), 2)
        numbered = renderer.shoot("new", str(deck), 2, number=True)
        assert numbered != plain, "display shots show the deck's slide number"
        assert renderer.shoot("new", str(deck), 2) == plain, "comparison shots omit it"
        # Missing assets must remain visible as missing assets, not force text fallback.
        page.evaluate("""() => {
          const slide = Reveal.getCurrentSlide();
          const image = document.createElement('img'); image.src = '/missing-review-image.png';
          slide.append(image); slide.style.backgroundImage = 'url(/missing-background.png)';
        }""")
        page.evaluate(review.READY_JS)
        assert renderer.shoot("new", str(deck), 2).startswith(b"\x89PNG")
        # Broken/undecodable video, a load that never finishes, a seek that
        # never finishes, and a blocked external embed do not drop the deck.
        page.evaluate("""() => {
          const slide = Reveal.getCurrentSlide();
          const broken = document.createElement('video'); broken.src = '/missing-video.mp4';
          slide.append(broken);
          for (const state of [0, 2]) {
            const stalled = document.createElement('video');
            Object.defineProperty(stalled, 'readyState', {get: () => state});
            Object.defineProperty(stalled, 'currentTime', {get: () => 1, set: () => {}});
            stalled.load = () => {}; slide.append(stalled);
          }
          const frame = document.createElement('iframe');
          frame.src = 'https://example.org/unavailable-embed'; slide.append(frame);
        }""")
        started = time.monotonic()
        assert renderer.shoot("new", str(deck), 2).startswith(b"\x89PNG")
        assert time.monotonic() - started < 6, (
            "media waits have short individual timeouts"
        )
        assert page.evaluate("""async () => {
          try { await fetch('https://example.org/deck-review-egress'); return false; }
          catch { return true; }
        }"""), "External requests must be blocked"
        page.evaluate("() => Reveal.getCurrentSlide().replaceChildren()")
        # Old tokens are the text as shown, so they start with the unchanged section line.
        head = page.evaluate(
            "() => {"
            + review.TEXT_FILTER_JS
            + " return shownText(Reveal.getCurrentSlide()).map(n => n.textContent)"
            + ".join(' ').split(/\\s+/).filter(Boolean); }"
        )
        page.evaluate(
            review.MARK_WORDS_JS, [review.MARK_CSS, head + ["deleted", "words"]]
        )
        assert page.locator(".present .dr-del").inner_text() == "deleted words"
        assert page.locator(".asta-slides-section .dr-del").count() == 0

    finally:
        renderer.close()


def typical_edit(root, deck, original):
    """Slides and a section inserted before others, one retitle and one text edit."""
    assert 'data-asta-section="1"' in original, "the example deck has sections"
    slides = changed.reveal_slides(original)
    shifted = re.sub(
        r'data-asta-section="(\d+)"',
        lambda m: f'data-asta-section="{int(m.group(1)) + 1}"',
        original,
    )
    first = re.search(r'<section\b[^>]*data-asta-section="2"', shifted)
    inserted = "".join(
        f'<section id="review-inserted-{i}" class="slide level2" data-asta-section="1" '
        f'data-asta-section-name="Inserted"><h2>Inserted slide {i}</h2>'
        f"<p>Brand new material {i}.</p></section>"
        for i in range(2)
    )
    after = shifted[: first.start()] + inserted + shifted[first.start() :]
    retitled = slides[-1]
    title = re.search(r"<h2[^>]*>(.*?)</h2>", retitled["body"], re.S)
    assert title, "the last slide has a title"
    after = after.replace(
        retitled["body"],
        retitled["body"].replace(title.group(1), title.group(1) + ", now retitled", 1),
        1,
    ).replace('id="' + retitled["id"] + '"', 'id="review-retitled"', 1)
    edited = next(
        slide
        for slide in slides[1:-1]
        if "<p>" in slide["body"] and "data-asta-section" not in slide["body"]
    )
    after = after.replace(
        edited["body"], edited["body"].replace("<p>", "<p>Freshly edited ", 1), 1
    )
    (root / "old" / deck).write_text(original)
    (root / "new" / deck).write_text(after)
    old, new = changed.reveal_slides(original), changed.reveal_slides(after)
    pairs = changed.match_slides(old, new)
    renderer = review.Renderer(root / "old", root / "new")
    try:
        rendered = review.review(
            str(deck),
            str(deck),
            str(root / "typical-images"),
            "images",
            old,
            new,
            pairs,
            renderer,
        )
        data = json.loads(
            rendered.split('class="dr-data">', 1)[1].split("</script>", 1)[0]
        )
        kinds = {item["n"]: item["kind"] for item in data["items"]}
        assert "look" not in kinds.values(), kinds
        assert list(kinds.values()).count("new") == 2, kinds
        assert data["removed"] == [], "the retitled slide is one edit"
        retitled_n = len(new)
        assert kinds[retitled_n] == "changed", kinds
        # Every changed slide has its words marked, the section line's new word included.
        old_text, new_text = (
            renderer.texts("old", str(deck)),
            renderer.texts("new", str(deck)),
        )
        page = renderer.page("new", str(deck))
        for n, kind in kinds.items():
            if kind != "changed":
                continue
            o = pairs[n - 1]
            assert old_text[o] != new_text[n - 1], n
            page.reload()
            page.wait_for_function("() => window.Reveal && Reveal.isReady()")
            page.evaluate(review.GOTO_JS, n - 1)
            page.evaluate(review.MARK_WORDS_JS, [review.MARK_CSS, old_text[o].split()])
            marks = page.locator(".dr-ins, .dr-del")
            assert marks.count() > 0, f"slide {n} has no marked words"
            if "Inserted" in new_text[n - 1] and "Inserted" not in old_text[o]:
                assert (
                    "Inserted"
                    in page.locator(".asta-slides-section .dr-ins").all_inner_texts()
                ), n
        section_changed = [
            n
            for n, k in kinds.items()
            if k == "changed" and "Inserted" in new_text[n - 1]
        ]
        assert len(section_changed) >= 3, kinds
    finally:
        renderer.close()


def interaction_edit(root, deck, original, artifacts):
    """An unchanged picture must not hide a changed link or control."""
    slides = changed.reveal_slides(original)
    link = '<p><a href="before.html">Read more</a></p>'
    notes = '<aside class="notes"><a href="old-notes.html">Speaker only</a></aside>'
    baseline = original.replace(slides[2]["body"], slides[2]["body"] + link, 1)
    baseline = baseline.replace(slides[3]["body"], slides[3]["body"] + notes, 1)
    after = baseline.replace('href="before.html"', 'href="after.html"').replace(
        'href="old-notes.html"', 'href="new-notes.html"'
    )
    (root / "old" / deck).write_text(baseline)
    (root / "new" / deck).write_text(after)
    old, new = changed.reveal_slides(baseline), changed.reveal_slides(after)
    renderer = review.Renderer(root / "old", root / "new")
    try:
        assert renderer.shoot("old", str(deck), 2) == renderer.shoot(
            "new", str(deck), 2
        )
        rendered = review.review(
            str(deck),
            str(deck),
            str(root / "new/interaction-images"),
            "interaction-images",
            old,
            new,
            changed.match_slides(old, new),
            renderer,
        )
        data = json.loads(
            rendered.split('class="dr-data">', 1)[1].split("</script>", 1)[0]
        )
        assert [i["n"] for i in data["items"] if i["kind"] == "changed"] == [3], data
        assert data["items"][3]["kind"] == "unchanged", "notes-only links are omitted"
        # Other declarative control changes are retained too, even without pixel changes.
        page = renderer.page("new", str(deck))
        page.evaluate(
            "() => Reveal.getSlides()[2].querySelector('a').target = '_blank'"
        )
        assert (
            renderer.interactions("new", str(deck))[2][0]["attributes"]["target"]
            == "_blank"
        )
    finally:
        renderer.close()
    (root / "new/interaction-review.html").write_text(
        "<!doctype html><meta charset='utf-8'>"
        + review.STYLE
        + rendered
        + review.SCRIPT
    )
    server = review._serve(str(root / "new"))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(
                f"http://127.0.0.1:{server.server_address[1]}/interaction-review.html"
            )
            note = page.locator(".dr-interactions")
            assert note.count() == 1
            assert (
                "before.html" in note.inner_text() and "after.html" in note.inner_text()
            )
            assert note.locator("a").count() == 0, "destinations are inert text"
            decode_review_images(page)
            page.screenshot(path=str(artifacts / "deck-review-link-edit.png"))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def decode_review_images(page):
    page.evaluate("""async () => {
      await Promise.all([...document.querySelectorAll('.dr-slide img')].map(i => {
        i.loading = 'eager'; return i.decode().catch(() => {});
      }));
    }""")


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
        typical_edit(root, deck, original)
        interaction_edit(root, deck, original, artifacts)
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
                assert "new deck has" in page.locator(".dr-count").inner_text()
                assert len(data["items"]) == len(slides), (
                    "Every unchanged run is inspectable"
                )
                assert page.locator(".dr-more").count() > 0
                # Headings are only the status, linked to the slide; the image shows the title.
                badges = page.locator(
                    ".dr-slide:not(.dr-removed) h3 a"
                ).all_text_contents()
                assert badges and all(
                    b
                    in {
                        "changed \u2197",
                        "changed look \u2197",
                        "new \u2197",
                        "unchanged \u2197",
                    }
                    for b in badges
                ), badges
                assert not any(
                    h.startswith("Slide")
                    for h in page.locator(".dr-slide h3").all_text_contents()
                )
                page.locator(".deck-review").scroll_into_view_if_needed()
                decode_review_images(page)
                assert all(
                    image.get_attribute("alt").startswith("Slide ")
                    for image in page.locator(".dr-slide img").all()
                )
                page.screenshot(path=str(artifacts / "deck-review-marked.png"))
                page.get_by_role("button", name="Clean", exact=True).click()
                assert (
                    page.locator('.dr-seg button[data-v="clean"]').get_attribute(
                        "aria-pressed"
                    )
                    == "true"
                )
                decode_review_images(page)
                assert (
                    page.locator(".dr-shot[data-clean] img")
                    .first.get_attribute("alt")
                    .endswith("(clean)")
                )
                page.screenshot(path=str(artifacts / "deck-review-clean.png"))
                page.get_by_role("button", name="Before / after", exact=True).click()
                assert page.locator(".dr-pair:visible").count() >= 2
                decode_review_images(page)
                page.screenshot(path=str(artifacts / "deck-review-before-after.png"))
                for image in page.locator(".dr-slide:visible img:visible").all():
                    image.scroll_into_view_if_needed()
                    image.wait_for(state="visible")
                    assert image.evaluate(
                        "(i, w) => i.complete && i.naturalWidth === w", DISPLAY_WIDTH
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
