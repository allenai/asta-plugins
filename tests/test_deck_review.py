"""Tests for the rendered deck review in What changed (no browser needed)."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
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


def test_render_decks_without_playwright_still_writes_the_page(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(what_changed, "load_deck_review", lambda: None)
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

    def interactions(self, side, deck):
        return [[] for _ in self.slides[side]]

    def shoot(self, side, deck, index, path=None, mark=None, number=False, words=None):
        self.calls.append((side, index, mark is not None) + ((True,) if number else ()))
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


def test_review_reuses_comparison_captures_and_numbers_display_shots(tmp_path):
    old, new = _slides("Before"), _slides("After")
    renderer = _Renderer(old, new)
    assert deck_review.review(
        "slides.html", "slides.html", str(tmp_path), "imgs", old, new, {0: 0}, renderer
    )
    assert renderer.calls.count(("new", 0, False)) <= 1
    # Before and after both show their deck's own number, while comparison shots omit it.
    assert ("new", 0, False, True) in renderer.calls
    assert ("new", 0, True, True) in renderer.calls
    assert ("old", 0, False, True) in renderer.calls


def test_notes_only_change_is_not_a_visible_edit():
    old, new = (
        _slides("Talk<aside>old notes</aside>"),
        _slides("Talk<aside>new notes</aside>"),
    )
    rows, _ = deck_review.classify(
        old, new, {0: 0}, lambda o, n: True, lambda o, n: True
    )
    assert rows == [("unchanged", 0, 0)]


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
        chromium=SimpleNamespace(launch=lambda **kw: SimpleNamespace(close=Mock())),
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


def test_site_server_does_not_follow_external_symlinks(tmp_path):
    from urllib.error import HTTPError
    from urllib.request import urlopen

    site = tmp_path / "site"
    site.mkdir()
    secret = tmp_path / "outside.txt"
    secret.write_text("must not be served")
    (site / "leak.txt").symlink_to(secret)
    (site / "directory").symlink_to(tmp_path, target_is_directory=True)
    server = deck_review._serve(str(site))
    try:
        for path in ("leak.txt", "directory/outside.txt"):
            with pytest.raises(HTTPError) as error:
                urlopen(f"http://127.0.0.1:{server.server_address[1]}/{path}")
            assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_renderer_routes_only_local_site_origins():
    from types import SimpleNamespace
    from unittest.mock import Mock

    renderer = object.__new__(deck_review.Renderer)
    renderer._bases = {"old": "http://127.0.0.1:123", "new": "http://127.0.0.1:456"}
    renderer._loaded = {}
    for url, allowed in [
        ("http://127.0.0.1:123/image.png", True),
        ("http://127.0.0.1:456/deck", True),
        ("https://example.org/beacon", False),
        ("http://127.0.0.1:789/private", False),
        ("http://127.0.0.1:123@evil.example/asset", False),
    ]:
        route = SimpleNamespace(
            request=SimpleNamespace(url=url), continue_=Mock(), abort=Mock()
        )
        renderer._route(route)
        assert route.continue_.called == allowed
        assert route.abort.called != allowed


def test_reorder_only_omits_invisible_text_changes():
    old = '<div class="reveal"><div class="slides"><section id="a"><h2>A</h2><aside class="notes">old</aside></section><section id="b"><h2>B</h2></section></div></div>'
    new = '<div class="reveal"><div class="slides"><section id="b"><h2>B</h2></section><section id="a"><h2>A</h2><aside class="notes">new</aside></section></div></div>'
    result = what_changed.slide_diff(
        old, new, "slides.html", "slides.html", decks=_FakeDecks(None)
    )
    assert "Slides reordered." in result[0]
    assert "slide-diff" not in result[0]


def test_retitled_slide_after_inserted_slides_is_one_edit():
    body = "<p>The example site is built by CI and deployed with every change, so readers always see the current workspace.</p>"
    old = [
        {"id": "intro", "body": "<h2>Intro</h2><p>Start.</p>", "anchor": "intro"},
        {
            "id": "a-live-example-rebuilt-from-each-release",
            "body": "<h2>A live example, rebuilt from each release</h2>" + body,
            "anchor": "a",
        },
    ]
    added = [
        {
            "id": f"new-{i}",
            "body": f"<h2>Added {i}</h2><p>Unrelated {i}.</p>",
            "anchor": f"n{i}",
        }
        for i in range(4)
    ]
    new = [
        old[0],
        *added,
        {
            "id": "a-live-example-rebuilt-on-every-merge-and-a-live-pr",
            "body": "<h2>A live example, rebuilt on every merge, and a live PR</h2>"
            + body,
            "anchor": "b",
        },
    ]
    assert what_changed.match_slides(old, new) == {0: 0, 5: 1}


def test_section_line_change_with_equal_markup_is_a_text_change():
    old = _slides("<h2>A</h2>", "<h2>B</h2>")
    new = _slides("<h2>A</h2>", "<h2>B</h2>")
    shown_old = ["Part A", "Part B"]
    shown_new = ["New part Part A", "Part B"]
    rows, _ = deck_review.classify(
        old,
        new,
        {0: 0, 1: 1},
        lambda o, n: False,
        lambda o, n: shown_old[o] == shown_new[n],
    )
    assert [kind for kind, _, _ in rows] == ["changed", "look"]


def test_link_destination_change_with_equal_text_and_image_is_retained(tmp_path):
    old = _slides('<h2>Resources</h2><a href="before.html">Read more</a>')
    new = _slides('<h2>Resources</h2><a href="after.html">Read more</a>')

    class LinkRenderer(_Renderer):
        def texts(self, side, deck):
            return ["Resources Read more"]

        def interactions(self, side, deck):
            return [
                [
                    {
                        "element": "a",
                        "label": "Read more",
                        "attributes": {"href": side + ".html"},
                    }
                ]
            ]

        def shoot(
            self, side, deck, index, path=None, mark=None, number=False, words=None
        ):
            return b"same pixels"

    rendered = deck_review.review(
        "slides.html",
        "slides.html",
        str(tmp_path),
        "imgs",
        old,
        new,
        {0: 0},
        LinkRenderer(old, new),
    )
    data = json.loads(rendered.split('class="dr-data">', 1)[1].split("</script>", 1)[0])
    item = data["items"][0]
    assert item["kind"] == "changed"
    assert item["interactions"]["before"][0]["attributes"] == {"href": "old.html"}
    assert item["interactions"]["after"][0]["attributes"] == {"href": "new.html"}


def test_large_rewritten_deck_keeps_edits_paired_with_quadratic_work(monkeypatch):
    old = _slides(
        *(
            f"<h2>Experiment {i:03d}</h2><p>Measurements for run {i:03d}, old version.</p>"
            for i in range(80)
        )
    )
    new = [
        {
            **s,
            "id": "regenerated-" + s["id"],
            "body": s["body"].replace("old version", "new version"),
        }
        for s in old
    ]
    new.insert(
        35, {"id": "added", "body": "<h2>ZZZZZZZZZZZZZZZZZZZZ</h2>", "anchor": "added"}
    )
    calls = 0
    original = what_changed.difflib.SequenceMatcher.ratio

    def ratio(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(what_changed.difflib.SequenceMatcher, "ratio", ratio)
    pairs = what_changed.match_slides(old, new)
    assert pairs == {i + (i >= 35): i for i in range(80)}
    assert calls <= 2 * len(old) * len(new) + 2 * len(new)


@pytest.mark.parametrize("insert_at", [0, 40, 80])
def test_large_insertion_keeps_every_rewritten_original_slide_paired(insert_at):
    old = _slides(
        *(
            f"<h2>Experiment {i:03d}</h2><p>Measurements for run {i:03d}, old version.</p>"
            for i in range(80)
        )
    )
    new = [
        {
            **s,
            "id": "regenerated-" + s["id"],
            "body": s["body"].replace("old version", "new version"),
        }
        for s in old
    ]
    inserted = [
        {"id": f"added-{i}", "body": "<h2>ZZZZZZZZZZZZZZZZZZZZ</h2>", "anchor": str(i)}
        for i in range(60)
    ]
    new[insert_at:insert_at] = inserted
    assert what_changed.match_slides(old, new) == {
        i + (60 if i >= insert_at else 0): i for i in range(80)
    }


def test_large_unrelated_decks_remain_additions_and_removals():
    old = _slides(*("<h2>AAAAAAAAAAAAAAAAAAAA</h2>" for _ in range(60)))
    new = [
        {**s, "id": "new-" + s["id"], "body": "<h2>ZZZZZZZZZZZZZZZZZZZZ</h2>"}
        for s in old
    ]
    assert what_changed.match_slides(old, new) == {}


def test_release_deck_closes_only_its_cached_documents():
    from unittest.mock import Mock

    renderer = object.__new__(deck_review.Renderer)
    before, after, other = Mock(), Mock(), Mock()
    renderer._pages = {
        ("old", "one.html"): before,
        ("new", "one.html"): after,
        ("new", "two.html"): other,
    }
    renderer.release_deck("one.html")
    before.close.assert_called_once()
    after.close.assert_called_once()
    other.close.assert_not_called()
    assert renderer._pages == {("new", "two.html"): other}


def test_a_failed_child_frame_does_not_discard_the_slide():
    from unittest.mock import Mock

    failed_frame = Mock()
    failed_frame.add_style_tag.side_effect = RuntimeError("frame detached")
    good_frame = Mock()
    page = Mock()
    page.main_frame = object()
    page.frames = [page.main_frame, failed_frame, good_frame]
    page.screenshot.return_value = b"PNG"
    renderer = object.__new__(deck_review.Renderer)
    renderer.page = lambda *args: page
    assert renderer.shoot("new", "deck.html", 0) == b"PNG"
    good_frame.evaluate.assert_called_once_with(deck_review.READY_JS)
    page.close.assert_not_called()


def test_display_shots_are_sharp_with_words_and_comparisons_stay_1x(tmp_path):
    from unittest.mock import Mock

    page = Mock()
    page.main_frame = object()
    page.frames = [page.main_frame]
    page.screenshot.return_value = b"PNG"
    page.evaluate.side_effect = lambda js, *a: (
        [["Hello", 0.1, 0.2, 0.05, 0.04]] if js == deck_review.WORDS_JS else None
    )
    renderer = object.__new__(deck_review.Renderer)
    renderer.page = lambda *args: page
    assert renderer.shoot("new", "deck.html", 0) == b"PNG"
    assert page.screenshot.call_args.kwargs["scale"] == "css"
    words = []
    renderer.shoot("new", "deck.html", 0, str(tmp_path / "s1.png"), words=words)
    assert page.screenshot.call_args.kwargs["scale"] == "device"
    assert words == [["Hello", 0.1, 0.2, 0.05, 0.04]]
    assert deck_review.DISPLAY_SCALE >= 2


def test_view_carries_each_images_selectable_words():
    text = {"a.png": [["Hello", 0.1, 0.2, 0.05, 0.04]]}
    page = deck_review.view([], [], 1, text)
    data = page.split('class="dr-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(data)["text"] == text
    assert ".dr-text span" in deck_review.STYLE and "paint(" in deck_review.SCRIPT


INLINE_SCRIPT = re.compile(r"(?is)<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>")


def _node_check(tmp_path, name, source):
    if shutil.which("node") is None:
        if os.environ.get("CI"):
            pytest.fail(
                "node is required in CI to parse the What changed pages' scripts"
            )
        pytest.skip("needs node")
    path = tmp_path / f"{name}.js"
    path.write_text(source)
    result = subprocess.run(
        ["node", "--check", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, f"{name}: {result.stderr}"


def test_view_page_scripts_parse(tmp_path):
    """Every executable inline script on a rendered deck view must parse.

    A Python escape such as an unescaped ``\\n`` turns into a real line break
    inside a JavaScript string, and the browser then runs none of the page.
    """
    item = {
        "kind": "changed",
        "n": 1,
        "title": "Slide",
        "marked": "m.png",
        "clean": "c.png",
        "before": "b.png",
        "link": "slides.html#/1",
    }
    text = {"m.png": [["Hi", 0.1, 0.2, 0.05, 0.04]]}
    page = (
        deck_review.STYLE + deck_review.SCRIPT + deck_review.view([item], [], 1, text)
    )
    scripts = [
        m["body"]
        for m in INLINE_SCRIPT.finditer(page)
        if "application/json" not in m["attrs"]
    ]
    assert scripts
    for i, body in enumerate(scripts):
        _node_check(tmp_path, f"deck-view-{i}", body)


@pytest.mark.parametrize("name", ["MODE_JS", "FOLD_JS", "PAPER_JS"])
def test_what_changed_page_scripts_parse(tmp_path, name):
    _node_check(tmp_path, name, getattr(what_changed, name))


def _deck(slides, head='<link rel="stylesheet" href="deck.css">'):
    sections = "".join(slides)
    return (
        f'<html><head>{head}</head><body><div class="reveal">'
        f'<div class="slides">{sections}</div></div></body></html>'
    )


def _static_renderer(tmp_path, old_doc, new_doc, files=None, new_files=None):
    for side, doc, extra in (("old", old_doc, files), ("new", new_doc, new_files)):
        root = tmp_path / side
        (root / "d").mkdir(parents=True)
        (root / "d" / "deck.html").write_text(doc)
        for name, data in {
            "d/deck.css": "h2{}",
            "d/a.png": "A",
            **(files or {}),
            **(extra or {}),
        }.items():
            (root / name).write_text(data)
    renderer = object.__new__(deck_review.Renderer)
    renderer._roots = {"old": str(tmp_path / "old"), "new": str(tmp_path / "new")}
    renderer._loaded = {"d/deck.html": {"/d/deck.html", "/d/deck.css"}}
    renderer._same_files = {}
    old = what_changed.reveal_slides(old_doc)
    new = what_changed.reveal_slides(new_doc)
    return renderer, old, new


SLIDE = '<section id="one"><h2>One</h2><img src="a.png"></section>'
EDITED = '<section id="two"><h2>Two</h2><p>edited</p></section>'


def test_identical_slide_and_inputs_skip_the_pixel_comparison(tmp_path):
    old_doc = _deck([SLIDE, '<section id="two"><h2>Two</h2></section>'])
    new_doc = _deck([SLIDE, EDITED])
    renderer, old, new = _static_renderer(tmp_path, old_doc, new_doc)
    assert renderer.same_static("d/deck.html", old[0], new[0])
    assert not renderer.same_static("d/deck.html", old[1], new[1])


def test_changed_section_background_is_compared_as_pixels(tmp_path):
    old_doc = _deck(
        [SLIDE.replace("<section ", '<section data-background-image="a.png" ')]
    )
    new_doc = _deck(
        [SLIDE.replace("<section ", '<section data-background-image="b.png" ')]
    )
    renderer, old, new = _static_renderer(tmp_path, old_doc, new_doc, {"d/b.png": "B"})
    # The normalised body ignores the <section> tag's attributes; the raw tag does not.
    assert old[0]["body"] == new[0]["body"]
    assert not renderer.same_static("d/deck.html", old[0], new[0])


@pytest.mark.parametrize(
    "change",
    [
        "image",  # a referenced file's bytes
        "head",  # the deck outside the slides
        "loaded",  # a file the deck loaded
        "style",  # a style element inside another slide
        "position",  # same slide, moved
        "live",  # content whose pixels can change on their own
    ],
)
def test_any_differing_input_falls_back_to_pixels(tmp_path, change):
    slide = (
        SLIDE.replace("<img", "<canvas></canvas><img") if change == "live" else SLIDE
    )
    old_doc = _deck([slide, '<section id="two"><h2>Two</h2></section>'])
    new_slides = [slide, EDITED]
    new_files = None
    head = '<link rel="stylesheet" href="deck.css">'
    if change == "image":
        new_files = {"d/a.png": "changed"}
    elif change == "head":
        head += "<style>h2{color:red}</style>"
    elif change == "loaded":
        new_files = {"d/deck.css": "h2{color:red}"}
    elif change == "style":
        new_slides[1] = EDITED.replace(
            "</section>", "<style>h2{color:red}</style></section>"
        )
    elif change == "position":
        new_slides = ['<section id="zero"><h2>Zero</h2></section>', slide]
    new_doc = _deck(new_slides, head)
    renderer, old, new = _static_renderer(
        tmp_path, old_doc, new_doc, new_files=new_files
    )
    index = 1 if change == "position" else 0
    assert not renderer.same_static("d/deck.html", old[0], new[index])


def test_review_takes_no_comparison_shots_of_statically_identical_slides(tmp_path):
    old, new = _slides("Same", "Before"), _slides("Same", "After")
    renderer = _Renderer(old, new)
    renderer.same_static = lambda deck, before, after: before["body"] == "Same"
    deck_review.review(
        "slides.html",
        "slides.html",
        str(tmp_path),
        "imgs",
        old,
        new,
        {0: 0, 1: 1},
        renderer,
    )
    comparison = [call for call in renderer.calls if len(call) == 3 and not call[2]]
    assert ("old", 0, False) not in comparison and ("new", 0, False) not in comparison


def test_outbound_anchor_is_not_a_loaded_resource(tmp_path):
    doc = _deck(
        ['<section id="one"><a href="https://example.org/paper">Read</a></section>']
    )
    renderer, old, new = _static_renderer(tmp_path, doc, doc)
    assert renderer.same_static("d/deck.html", old[0], new[0])


def test_inline_image_data_is_read_whole(tmp_path):
    slide = '<section id="one"><img src="data:image/svg+xml;base64,QUJDRA=="></section>'
    doc = _deck([slide])
    renderer, old, new = _static_renderer(tmp_path, doc, doc)
    assert renderer.same_static("d/deck.html", old[0], new[0])
    new[0]["raw"] = new[0]["raw"].replace("QUJDRA", "Rk9PQg")
    assert not renderer.same_static("d/deck.html", old[0], new[0])


def test_live_marks_only_changed_words_outside_tags_and_scripts():
    old = '<section id="a"><h2>Attention weights</h2><p>the context</p></section>'
    new = (
        '<section id="a"><h2>Attention weights</h2>'
        "<script>var x = 1</script><p>the available context</p></section>"
    )
    deleted, inserted = deck_review.word_changes(old, new)
    assert deleted == set()
    assert [deck_review.slide_words(new)[i] for i in inserted] == ["available"]
    marked = deck_review.mark_words(new, inserted, "ins")
    assert '<ins class="dr-live">available</ins>' in marked
    assert "<script>var x = 1</script>" in marked
    assert deck_review.slide_words(marked) == deck_review.slide_words(new)


def test_marked_deck_touches_only_the_marked_slide():
    doc = (
        "<html><head></head><body><div class='reveal'><div class='slides'>"
        '<section id="a"><p>one two</p></section>'
        '<section id="b"><p>three four</p></section>'
        "</div></div></body></html>"
    )
    slides = what_changed.reveal_slides(doc)
    assert [s["id"] for s in slides] == ["a", "b"]
    out = deck_review.marked_deck(doc, slides, {1: {0}}, "del")
    assert '<del class="dr-live">three</del> four' in out
    assert '<section id="a"><p>one two</p></section>' in out
    assert deck_review.LIVE_MARK_CSS + "</head>" in out


def test_live_rows_classifies_words_and_look_without_a_browser():
    old = [
        {"raw": "<section><p>same</p></section>", "body": "same"},
        {"raw": "<section><p>old words</p></section>", "body": "old words"},
        {"raw": '<section><img src="a.png"><p>pic</p></section>', "body": "pic"},
        {"raw": "<section><p>gone</p></section>", "body": "gone"},
    ]
    new = [
        {"raw": "<section><p>same</p></section>", "body": "same"},
        {"raw": "<section><p>new words</p></section>", "body": "new words"},
        {"raw": '<section><img src="a.png"><p>pic</p></section>', "body": "pic"},
        {"raw": "<section><p>added</p></section>", "body": "added"},
    ]
    pairs = {0: 0, 1: 1, 2: 2}
    rows, removed = deck_review.live_rows(
        old, new, pairs, lambda before, after: "img" not in after["raw"]
    )
    assert [kind for kind, _, _ in rows] == ["unchanged", "changed", "look", "new"]
    assert removed == [3]


def _static_files(tmp_path, old_doc, new_doc, files=None, new_files=None):
    _, old, new = _static_renderer(tmp_path, old_doc, new_doc, files, new_files)
    return (
        deck_review.StaticFiles(str(tmp_path / "old"), str(tmp_path / "new")),
        old,
        new,
    )


def test_static_files_skip_identical_slides_without_a_browser(tmp_path):
    old_doc = _deck([SLIDE, '<section id="two"><h2>Two</h2></section>'])
    new_doc = _deck([SLIDE, EDITED])
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    assert files.same_static("d/deck.html", old[0], new[0])
    assert not files.same_static("d/deck.html", old[1], new[1])


def test_static_files_follow_the_decks_stylesheets(tmp_path):
    doc = _deck([SLIDE])
    css = {"d/deck.css": '@import "more.css";', "d/more.css": "h2{}"}
    files, old, new = _static_files(
        tmp_path, doc, doc, css, {"d/more.css": "h2{color:red}"}
    )
    assert "/d/more.css" in files.loaded("d/deck.html", new[0]["frame"])
    assert not files.same_static("d/deck.html", old[0], new[0])


def test_static_files_compare_slide_images_and_ignore_outbound_links(tmp_path):
    slide = SLIDE.replace(
        "</section>", '<a href="https://arxiv.org/abs/1706.03762">paper</a></section>'
    )
    doc = _deck([slide])
    files, old, new = _static_files(tmp_path, doc, doc)
    assert files.same_static("d/deck.html", old[0], new[0])
    files, old, new = _static_files(tmp_path / "b", doc, doc, None, {"d/a.png": "B"})
    assert not files.same_static("d/deck.html", old[0], new[0])


def test_static_files_read_inline_data_images_whole(tmp_path):
    data = '<img src="data:image/svg+xml,%3Csvg%20a=%221,2%22/%3E">'
    doc = _deck([SLIDE.replace("</section>", data + "</section>")])
    files, old, new = _static_files(tmp_path, doc, doc)
    assert files.same_static("d/deck.html", old[0], new[0])


def test_live_report_marks_both_decks_without_browser(tmp_path):
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()

    def deck(word):
        return (
            '<html><head></head><body><div class="reveal"><div class="slides">'
            '<section id="a"><h2>Hello ' + word + "</h2></section>"
            '<section id="b"><h2>Same</h2></section></div></div></body></html>'
        )

    before, after = deck("old"), deck("new")
    (old_root / "deck.html").write_text(before)
    (new_root / "deck.html").write_text(after)
    slides_old = what_changed.reveal_slides(before)
    slides_new = what_changed.reveal_slides(after)
    renderer = what_changed.DeckRenderer(
        deck_review,
        str(old_root),
        str(new_root),
        str(new_root / "what-changed-decks"),
        "what-changed-decks",
    )
    body = renderer.review(
        "deck.html", "deck.html", slides_old, slides_new, {0: 0, 1: 1}
    )
    assert "<iframe " in body and "details" in body and "<template>" in body
    assert 'data-step="next"' in body
    assert (
        '<del class="dr-live">old</del>'
        in (new_root / "what-changed-decks/before/deck.html").read_text()
    )
    assert (
        '<ins class="dr-live">new</ins>'
        in (new_root / "what-changed-decks/after/deck.html").read_text()
    )
    assert not list(new_root.rglob("*.png"))
    assert not (new_root / "what-changed-decks/after/what-changed-decks").exists()


def test_live_view_script_parses(tmp_path):
    _node_check(
        tmp_path,
        "live-view",
        deck_review.LIVE_SCRIPT.removeprefix("<script>").removesuffix("</script>"),
    )


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


SELF_CONTAINED_HEAD = (
    '<style>.reveal{background:url("data:image/svg+xml,%3Csvg/%3E")}</style>'
    '<script>const css = "h2{background:url(\\"x.png\\")}";</script>'
)


def test_self_contained_deck_folds_its_unchanged_slides(tmp_path):
    """Text in scripts, quoted data URLs and absent paths load no differing file."""
    styled = (
        '<section id="one" style="background-image:url(&quot;data:image/png;'
        'base64,AAAA&quot;)"><h2>One</h2></section>'
    )
    old_doc = _deck(
        [styled, '<section id="two"><h2>Two</h2></section>'], SELF_CONTAINED_HEAD
    )
    new_doc = _deck([styled, EDITED], SELF_CONTAINED_HEAD)
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    assert files.same_static("d/deck.html", old[0], new[0])
    body, _, _ = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {0: 0, 1: 1}, files, "b", "a"
    )
    assert "1 changed or new; 0 removed; 2 slides" in body
    assert "1 unchanged slides" in body
    assert "changed in look" not in body


def test_live_frames_open_the_deck_full_page_not_embedded(tmp_path):
    old_doc = _deck(['<section id="one"><h2>One</h2></section>'])
    new_doc = _deck(['<section id="one"><h2>Uno</h2></section>'])
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    body, _, _ = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {0: 0}, files, "b", "a"
    )
    assert 'src="a?dr-slide=0#/one"' in body and "embedded" not in body


def test_live_frames_open_at_their_own_slide(tmp_path):
    """Reveal can ignore the hash, so each marked deck moves to ``dr-slide`` itself."""
    old_doc = _deck(
        [
            '<section id="one"><h2>One</h2></section>',
            '<section id="two"><h2>Two</h2></section>',
        ]
    )
    new_doc = _deck(['<section id="one"><h2>One</h2></section>', EDITED])
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    body, old_marked, new_marked = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {0: 0, 1: 1}, files, "b", "a"
    )
    assert 'data-dr-slide="1"' in body and "?dr-slide=1#/" in body
    for doc in (old_marked, new_marked):
        assert deck_review.GOTO_SCRIPT in doc
        assert doc.index(deck_review.GOTO_SCRIPT) < doc.lower().rindex("</body>")


def test_slides_shifted_by_an_inserted_slide_are_not_changed_in_look(tmp_path):
    """A live frame's slide number is no change; only a new slide is shown."""
    old_doc = _deck(
        [
            '<section id="one"><h2>One</h2></section>',
            '<section id="two"><h2>Two</h2></section>',
        ]
    )
    new_doc = _deck(
        [
            '<section id="new"><h2>New</h2></section>',
            '<section id="one"><h2>One</h2></section>',
            '<section id="two"><h2>Two</h2></section>',
        ]
    )
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    body, _, _ = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {1: 0, 2: 1}, files, "b", "a"
    )
    assert "1 changed or new; 0 removed; 3 slides" in body
    assert "changed in look" not in body
