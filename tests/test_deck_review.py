"""Tests for the rendered deck review in What changed (no browser needed)."""

import importlib.util
import json
from pathlib import Path

import pytest

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


def test_context_keeps_complete_unchanged_runs():
    rows = [("unchanged", i, i) for i in range(10)]
    rows[5] = ("changed", 5, 5)
    assert deck_review.context(rows) == list(range(10))


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


def test_reordered_slides_survive_rendered_and_empty_views():
    old = _slides("<h2>One</h2>", "<h2>Two</h2>")
    new = [old[1], old[0]]
    for body in (None, "<i>rendered changes</i>"):
        result = what_changed.slide_diff(
            "old",
            "new",
            "slides.html",
            "slides.html",
            old=old,
            new=new,
            decks=_FakeDecks(body),
        )
        assert "Slides reordered." in result[0]
        if body:
            assert body in result[0]


def test_heavily_rewritten_slide_with_same_id_remains_paired():
    old = _slides("<h2>AAAAAAAAAAAAAAAAAAAA</h2>")
    new = _slides("<h2>ZZZZZZZZZZZZZZZZZZZZ</h2>")
    assert what_changed.match_slides(old, new) == {0: 0}


def test_json_title_cannot_enter_script_double_escape_state():
    title = "<!--<script></script><title>still data"
    page = deck_review.view([{"title": title}], [], 1)
    data = page.split('class="dr-data">', 1)[1].split("</script>", 1)[0]
    assert "<" not in data
    assert json.loads(data)["items"][0]["title"] == title


class _Renderer:
    def __init__(self, old, new):
        self.slides = {"old": old, "new": new}
        self.calls = []

    def slide_ids(self, side, deck):
        return [s["id"] for s in self.slides[side]]

    def texts(self, side, deck):
        return [s["body"] for s in self.slides[side]]

    def shoot(self, side, deck, index, path=None, mark=None):
        self.calls.append((side, index, mark is not None))
        data = self.slides[side][index]["body"].encode()
        if path:
            Path(path).write_bytes(data)
        return data


def test_parser_browser_order_mismatch_fails_before_capture(tmp_path):
    import pytest

    old = _slides("One", "Two")
    renderer = _Renderer(old, list(reversed(old)))
    with pytest.raises(ValueError, match="slide order"):
        deck_review.review(
            "slides.html",
            "slides.html",
            str(tmp_path),
            "imgs",
            old,
            old,
            {0: 0, 1: 1},
            renderer,
        )
    assert renderer.calls == []


def test_review_reuses_captured_clean_images(tmp_path):
    old, new = _slides("Before"), _slides("After")
    renderer = _Renderer(old, new)
    assert deck_review.review(
        "slides.html", "slides.html", str(tmp_path), "imgs", old, new, {0: 0}, renderer
    )
    assert renderer.calls.count(("new", 0, False)) == 1
    assert renderer.calls.count(("old", 0, False)) == 1


def test_notes_only_change_is_not_a_visible_edit():
    old, new = (
        _slides("Talk<aside>old notes</aside>"),
        _slides("Talk<aside>new notes</aside>"),
    )
    rows, _ = deck_review.classify(
        old, new, {0: 0}, lambda o, n: True, lambda o, n: True
    )
    assert rows == [("unchanged", 0, 0)]


def test_failed_browser_launch_is_not_retried_and_cleans_partial_images(tmp_path):
    from types import SimpleNamespace

    def fail(*args):
        calls.append(args)
        raise RuntimeError("no browser")

    calls = []
    partial = tmp_path / "slides.html"
    partial.mkdir()
    (partial / "partial.png").touch()
    decks = what_changed.DeckRenderer(
        SimpleNamespace(Renderer=fail), "old", "new", str(tmp_path), "imgs"
    )
    for _ in range(2):
        assert (
            decks.review("slides.html", "slides.html", [], _slides("One"), {}) is False
        )
    assert len(calls) == 1
    assert not partial.exists()


def test_output_images_are_relative_to_output_page_and_stale_files_removed(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    images = new / "assets/review"
    images.mkdir(parents=True)
    (images / "stale.png").touch()
    captured = []

    class Decks:
        def __init__(self, *args):
            captured.append(args)
            self.used = False

        def close(self):
            pass

    monkeypatch.setattr(what_changed, "load_deck_review", lambda: SimpleNamespace())
    monkeypatch.setattr(what_changed, "DeckRenderer", Decks)
    out = new / "what-changed.html"
    what_changed.main(
        [
            "--old",
            str(old),
            "--new",
            str(new),
            "--out",
            str(out),
            "--render-decks",
            str(images),
        ]
    )
    assert captured[0][-1] == "assets/review"
    assert not (images / "stale.png").exists()


def test_failed_renderer_initialization_closes_all_started_resources(
    tmp_path, monkeypatch
):
    from types import ModuleType, SimpleNamespace
    from unittest.mock import Mock

    import pytest

    server = SimpleNamespace(
        server_address=("127.0.0.1", 12345), shutdown=Mock(), server_close=Mock()
    )
    pw = SimpleNamespace(
        chromium=SimpleNamespace(
            launch=Mock(side_effect=RuntimeError("launch failed"))
        ),
        stop=Mock(),
    )
    api = ModuleType("playwright.sync_api")
    api.sync_playwright = lambda: SimpleNamespace(start=lambda: pw)
    monkeypatch.setitem(__import__("sys").modules, "playwright.sync_api", api)
    monkeypatch.setattr(deck_review, "_serve", lambda root: server)
    with pytest.raises(RuntimeError, match="launch failed"):
        deck_review.Renderer(tmp_path, tmp_path)
    pw.stop.assert_called_once()
    assert server.shutdown.call_count == 2
    assert server.server_close.call_count == 2


def test_generated_directory_cannot_replace_a_site_root(tmp_path):
    import pytest

    (tmp_path / "keep.html").write_text("keep")
    with pytest.raises(SystemExit):
        what_changed.main(
            [
                "--old",
                str(tmp_path),
                "--new",
                str(tmp_path),
                "--out",
                str(tmp_path / "diff.html"),
                "--render-decks",
                str(tmp_path),
            ]
        )
    assert (tmp_path / "keep.html").read_text() == "keep"


@pytest.mark.parametrize("location", ["outside", "symlink", "parent-symlink"])
def test_image_cleanup_rejects_unsafe_locations_without_deleting(tmp_path, location):
    old, new, outside = tmp_path / "old", tmp_path / "new", tmp_path / "outside"
    for path in (old, new, outside):
        path.mkdir()
    target = outside if location == "outside" else new / "keep"
    target.mkdir(exist_ok=True)
    (target / "keep.txt").write_text("keep")
    if location == "outside":
        images = target
    elif location == "symlink":
        images = new / "images"
        images.symlink_to(target, target_is_directory=True)
    else:
        alias = new / "alias"
        alias.symlink_to(target, target_is_directory=True)
        images = alias / "generated"
        images.mkdir()
        (images / "keep.txt").write_text("keep")
    with pytest.raises(SystemExit):
        what_changed.main(
            [
                "--old",
                str(old),
                "--new",
                str(new),
                "--out",
                str(new / "diff.html"),
                "--render-decks",
                str(images),
            ]
        )
    assert (target / "keep.txt").read_text() == "keep"
    if location == "parent-symlink":
        assert (images / "keep.txt").read_text() == "keep"


def test_old_and_new_sites_have_independent_origin_roots(tmp_path, monkeypatch):
    from types import ModuleType, SimpleNamespace
    from unittest.mock import Mock
    from urllib.request import urlopen

    pw = SimpleNamespace(
        chromium=SimpleNamespace(launch=lambda: SimpleNamespace(close=Mock())),
        stop=Mock(),
    )
    api = ModuleType("playwright.sync_api")
    api.sync_playwright = lambda: SimpleNamespace(start=lambda: pw)
    monkeypatch.setitem(__import__("sys").modules, "playwright.sync_api", api)
    for side in ("old", "new"):
        (tmp_path / side / "images").mkdir(parents=True)
        (tmp_path / side / "images/chart.svg").write_text(side)
    renderer = deck_review.Renderer(tmp_path / "old", tmp_path / "new")
    try:
        assert renderer._bases["old"] != renderer._bases["new"]
        for side in ("old", "new"):
            with urlopen(renderer._bases[side] + "/images/chart.svg") as response:
                assert response.read().decode() == side
    finally:
        renderer.close()
