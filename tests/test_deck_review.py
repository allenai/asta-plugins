"""Tests for the rendered deck review in What changed (no browser needed)."""

import importlib.util
import json
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "plugins/asta-tools/skills/workspace/assets"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ASSETS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deck_review = _load("deck_review", "deck-review.py")
what_changed = _load("what_changed_for_decks", "what-changed.py")


def _slides(*bodies):
    return [
        {"id": f"s{i}", "body": body, "anchor": f"s{i}"}
        for i, body in enumerate(bodies)
    ]


def test_classify_marks_text_image_new_and_removed_slides():
    old = _slides("<h2>A</h2>", "<h2>B</h2>", "<h2>C</h2>", "<h2>D</h2>")
    new = _slides("<h2>A</h2>", "<h2>B</h2> more", "<h2>C</h2>", "<h2>E</h2>")
    pairs = {0: 0, 1: 1, 2: 2}
    rows, removed = deck_review.classify(old, new, pairs, lambda o, n: o != 2)
    assert [kind for kind, _, _ in rows] == ["unchanged", "changed", "look", "new"]
    assert removed == [3]


def test_classify_without_images_treats_equal_markup_as_unchanged():
    old = _slides("<h2>A</h2>")
    rows, removed = deck_review.classify(old, _slides("<h2>A</h2>"), {0: 0})
    assert rows == [("unchanged", 0, 0)] and removed == []


def test_context_shows_two_unchanged_slides_around_each_change():
    rows = [("unchanged", i, i) for i in range(10)]
    rows[5] = ("changed", 5, 5)
    assert deck_review.context(rows) == [3, 4, 5, 6, 7]


def test_slide_title_reads_the_heading_text():
    slide = {"body": '<h2 class="x">The <em>question</em>\n here</h2><p>body</p>'}
    assert deck_review.slide_title(slide) == "The question here"


def test_view_embeds_data_without_closing_its_script():
    items = [{"n": 1, "kind": "new", "title": "</script><b>", "clean": "a.png"}]
    page = deck_review.view(items, [], 3)
    data = page.split('class="dr-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(data)["items"][0]["title"] == "</script><b>"


class _FakeDecks:
    def __init__(self, body):
        self.body = body

    def review(self, rel, link, old, new, pairs):
        return self.body


def test_slide_diff_uses_the_rendered_view_and_falls_back_to_text():
    doc = '<div class="reveal"><div class="slides"><section id="a"><h2>{}</h2></section></div></div>'
    old, new = doc.format("Old"), doc.format("New")
    rendered = what_changed.slide_diff(
        old,
        new,
        "slides/x/slides.html",
        "slides/x/slides.html",
        decks=_FakeDecks("<i>view</i>"),
    )
    assert "<i>view</i>" in rendered[0]
    text = what_changed.slide_diff(
        old,
        new,
        "slides/x/slides.html",
        "slides/x/slides.html",
        decks=_FakeDecks(False),
    )
    assert "<i>view</i>" not in text[0] and "New" in text[0]
    assert (
        what_changed.slide_diff(
            old, new, "slides/x/slides.html", "s.html", decks=_FakeDecks(None)
        )
        is None
    )


def test_render_decks_without_playwright_still_writes_the_page(tmp_path, capsys):
    out = tmp_path / "what-changed.html"
    what_changed.main(
        [
            "--old",
            str(tmp_path),
            "--new",
            str(tmp_path),
            "--out",
            str(out),
            "--render-decks",
            str(tmp_path / "what-changed-decks"),
        ]
    )
    assert out.read_text().startswith("<!doctype html>")


def test_matching_does_not_pair_unrelated_added_and_removed_slides():
    old = [
        {
            "id": "removed",
            "body": "<h2>Original experiment methodology</h2>",
            "anchor": "removed",
        }
    ]
    new = [{"id": "added", "body": "<h2>ZZZZ</h2>", "anchor": "added"}]
    assert what_changed.match_slides(old, new) == {}
