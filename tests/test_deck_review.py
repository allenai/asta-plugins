"""Tests for the rendered deck review in What changed (no browser needed)."""

import importlib.util
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


def test_slide_title_reads_the_heading_text():
    slide = {"body": '<h2 class="x">The <em>question</em>\n here</h2><p>body</p>'}
    assert deck_review.slide_title(slide) == "The question here"


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


def test_notes_only_change_is_not_a_visible_edit():
    old, new = (
        _slides("Talk<aside>old notes</aside>"),
        _slides("Talk<aside>new notes</aside>"),
    )
    rows, _ = deck_review.classify(
        old, new, {0: 0}, lambda o, n: True, lambda o, n: True
    )
    assert rows == [("unchanged", 0, 0)]


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


@pytest.mark.parametrize("name", ["MODE_JS", "FOLD_JS", "PAPER_JS"])
def test_what_changed_page_scripts_parse(tmp_path, name):
    _node_check(tmp_path, name, getattr(what_changed, name))


def _deck(slides, head='<link rel="stylesheet" href="deck.css">'):
    sections = "".join(slides)
    return (
        f'<html><head>{head}</head><body><div class="reveal">'
        f'<div class="slides">{sections}</div></div></body></html>'
    )


SLIDE = '<section id="one"><h2>One</h2><img src="a.png"></section>'
EDITED = '<section id="two"><h2>Two</h2><p>edited</p></section>'


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
    # No build controls: every build is shown and navigation is off in each frame.
    assert "data-step" not in body and "fragments=false" in body
    assert "keyboard=false" in body and "touch=false" in body
    # What changed's page has one header and one control: the deck's own bar is not drawn.
    assert "dr-bar" not in body and "dr-seg" not in body
    decks = new_root / "what-changed-decks"
    assert (
        'dr-live">'
        not in (decks / "before/deck.html").read_text().split("</style>")[-1]
    )
    assert (
        'dr-live">' not in (decks / "after/deck.html").read_text().split("</style>")[-1]
    )
    # Changes marked: removed words struck and added words marked on the one slide.
    marked = (decks / "after/deck.marked.html").read_text()
    assert (
        'Hello <del class="dr-live">old</del> <ins class="dr-live">new</ins>' in marked
    )
    # Each frame is one slide's document, beside the deck.
    assert "deck.frame-marked-1.html?" in body and "deck.marked.html?" not in body
    frame = (decks / "after/deck.frame-marked-1.html").read_text()
    assert (
        'Hello <del class="dr-live">old</del> <ins class="dr-live">new</ins>' in frame
    )
    assert "Same" not in frame and frame.count("<section") == 2
    assert not list(new_root.rglob("*.png"))
    assert not (new_root / "what-changed-decks/after/what-changed-decks").exists()


def _large_deck(words, count=40):
    """A self-contained deck like Quarto's: fonts and scripts inline, images as data."""
    import base64
    import hashlib
    from urllib.parse import quote

    def blob(seed, size):
        out, block = b"", seed.encode()
        while len(out) < size:
            block = hashlib.sha256(block).digest()
            out += block
        return out[:size]

    fonts = base64.b64encode(blob("font", 600_000)).decode()
    css = "@font-face{font-family:F;src:url(data:font/woff2;base64," + fonts + ")}"
    head = (
        f'<link href="data:text/css,{quote(css, safe="")}" rel="stylesheet">'
        f"<script>{'var a=1;' * 15_000}</script>"
    )
    images = [blob(f"slide {i}", 60_000) for i in range(count)]
    slides = [
        f'<section id="s{i}"><h2>Slide {i} {words}</h2><p>Text of slide {i}.</p>'
        f'<img src="data:image/png;base64,{base64.b64encode(image).decode()}">'
        "</section>"
        for i, image in enumerate(images)
    ]
    return _deck(slides, head), images, css


def test_a_large_deck_gets_small_frames_not_a_copy_of_the_deck_each(tmp_path):
    """Every slide of a big changed deck is its own small document.

    A frame that is the whole self-contained deck (here 3 MB, like a real talk's
    6 MB) must be fetched and parsed for each slide, so the page stays blank.
    """
    old_doc, _, _ = _large_deck("before")
    new_doc, images, css = _large_deck("after")
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    for root, doc in ((old_root, old_doc), (new_root, new_doc)):
        root.mkdir()
        (root / "deck.html").write_text(doc)
    assert len(new_doc) > 3_000_000
    old, new = what_changed.reveal_slides(old_doc), what_changed.reveal_slides(new_doc)
    renderer = what_changed.DeckRenderer(
        deck_review,
        str(old_root),
        str(new_root),
        str(new_root / "what-changed-decks"),
        "what-changed-decks",
    )
    body = renderer.review(
        "deck.html", "deck.html", old, new, {i: i for i in range(len(new))}
    )
    decks = new_root / "what-changed-decks"
    sources = re.findall(r'data-src="what-changed-decks/([^"?]+)\?', body)
    for source in set(sources):
        frame = (decks / source).read_text()
        assert len(frame) < 100_000, (source, len(frame))
    # Marked, clean, before and after for each of the 40 changed slides.
    assert len(sources) == 4 * len(images)
    assert len(set(sources)) == 3 * len(images)
    # A frame keeps its slide's place and only that slide's content.
    frame = (decks / "after/deck.frame-marked-8.html").read_text()
    assert frame.count("<section") == len(images)
    assert "Slide 7 " in frame and "Slide 6 " not in frame
    assert '<ins class="dr-live">after</ins>' in frame
    # Its big pieces are shared files with the original bytes, found from the frame.
    shared = {
        match[1]: (decks / "after" / match[0] / match[1]).resolve()
        for match in re.findall(
            r'(?:src|href)="((?:\.\./)+frame-assets)/([^"]+)"', frame
        )
    }
    assert len(shared) == 3, shared
    for name, path in shared.items():
        assert path.parent == (decks / "frame-assets").resolve() and path.is_file()
    contents = {name: path.read_bytes() for name, path in shared.items()}
    assert css.encode() in contents.values()
    assert images[7] in contents.values()
    # The same fonts and scripts serve every frame, so the decks are not copied again.
    assets = sum(path.stat().st_size for path in (decks / "frame-assets").iterdir())
    frames = sum(path.stat().st_size for path in decks.rglob("deck.frame-*.html"))
    assert assets + frames < len(new_doc) * 3


def test_frames_keep_the_deck_wide_style_and_hidden_slides():
    doc = _deck(
        [
            '<section id="a"><style>h2{color:red}</style><h2>A</h2></section>',
            '<section id="b" data-visibility="hidden"><h2>B</h2></section>',
            '<section id="c"><h2>C</h2></section>',
        ]
    )
    slides = what_changed.reveal_slides(doc)
    frame = deck_review.FrameDocs(doc, slides, deck_review.FrameAssets("x/")).render(2)
    assert "<h2>C</h2>" in frame and "<h2>A</h2>" not in frame
    # A slide's own style may restyle the kept slide; hidden stays hidden.
    assert "<style>h2{color:red}</style>" in frame
    assert '<section data-visibility="hidden"></section>' in frame


def test_only_pieces_that_load_the_same_from_a_file_move_out_of_a_frame():
    assets = deck_review.FrameAssets("x/")
    big = "a" * deck_review.BIG_BLOCK
    own_path = f"<script>document.currentScript.src;{big}</script>"
    relative = f"<style>a{{background:url(img.png)}}{big}</style>"
    typed = f'<script type="module">{big}</script>'
    assert assets.move(own_path + relative + typed) == own_path + relative + typed
    moved = assets.move(f"<style>p{{}}{big}</style><script>{big}</script>")
    assert moved.count("x/") == 2 and len(assets.files) == 2
    # A data stylesheet and a data image are decoded to their own bytes.
    link = f'<link href="data:text/css,a%7B%7D{big}" rel="stylesheet">'
    assert 'href="x/' in assets.move(link) and 'rel="stylesheet"' in assets.move(link)
    assert ("a{}" + big).encode() in assets.files.values()
    import base64

    encoded = "A" * (deck_review.BIG_DATA + 4)
    assert assets.move(f'<img src="data:image/png;base64,{encoded}">').startswith(
        '<img src="x/'
    )
    assert base64.b64decode(encoded) in assets.files.values()


def test_before_frame_of_an_unchanged_slide_shows_the_old_slide(tmp_path):
    """Before is always the old deck's slide, even where the new deck shifts it."""

    def deck(*slides):
        return _deck([f"<section>{slide}</section>" for slide in slides])

    note = "<aside class='notes'>{}</aside>"
    old_doc = deck("<h2>A</h2>" + note.format("old note"), "<h2>B</h2>")
    new_doc = deck("<h2>X</h2>", "<h2>A</h2>" + note.format("new note"), "<h2>B</h2>")
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    body, _, _, _, frames = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {1: 0, 2: 1}, files, "b", "a"
    )
    # Slides with no id are found by position: A is slide 1 before, 2 after.
    for title, anchor in (("A", "0"), ("B", "1")):
        card = body.split(f"Slide {'2' if title == 'A' else '3'}: {title}")[1]
        before = re.search(
            rf'<figcaption>Before</figcaption><iframe[^>]*data-src="b\.frame-before-(\d+)[^"]*#/{anchor}"',
            card,
        )
        assert before, (title, card[:600])
        frame = frames["before", f"d/deck.frame-before-{before.group(1)}.html"]
        # The old document's frame, whose kept slide is the one the hash names.
        assert f"<h2>{title}</h2>" in frame and "<h2>X</h2>" not in frame
        assert ("old note" in frame) == (title == "A") and "new note" not in frame


def test_slide_frames_are_sandboxed_to_scripts_only(tmp_path):
    # A deck's own scripts must not reach the report: no same-origin, navigation,
    # popups or forms, so that a frame runs in an opaque origin.
    doc = _deck(["<section><h2>A</h2></section>", "<section><h2>B</h2></section>"])
    new_doc = _deck(["<section><h2>A</h2></section>", "<section><h2>C</h2></section>"])
    files, old, new = _static_files(tmp_path, doc, new_doc)
    body, _, _, _, _ = deck_review.live_review(
        "d/deck.html", doc, new_doc, old, new, {0: 0, 1: 1}, files, "b", "a"
    )
    tags = re.findall(r"<iframe\b[^>]*>", body)
    assert tags
    for tag in tags:
        assert re.findall(r'\bsandbox="([^"]*)"', tag) == ["allow-scripts"], tag


def test_emptied_slides_keep_the_section_metadata_the_theme_reads():
    doc = _deck(
        [
            '<section id="a" data-asta-section="1" data-asta-section-name="Intro"'
            ' data-background-image="x.png" class="big"><h2>A</h2></section>',
            '<section id="b" data-asta-section="2" data-asta-section-name="Method">'
            "<h2>B</h2></section>",
        ]
    )
    slides = what_changed.reveal_slides(doc)
    frame = deck_review.FrameDocs(doc, slides, deck_review.FrameAssets("x/")).render(1)
    assert "<h2>B</h2>" in frame and "<h2>A</h2>" not in frame
    # The section headline lists every section, so the emptied slide names its own.
    assert (
        '<section data-asta-section="1" data-asta-section-name="Intro"></section>'
        in frame
    )
    # Nothing that draws the emptied slide: no background, id or class.
    assert "x.png" not in frame and 'class="big"' not in frame


def test_live_report_of_an_unchanged_deck_is_none(tmp_path):
    doc = (
        '<html><head></head><body><div class="reveal"><div class="slides">'
        '<section id="a"><h2>Same</h2></section></div></div></body></html>'
    )
    for side in ("old", "new"):
        (tmp_path / side).mkdir()
        (tmp_path / side / "deck.html").write_text(doc)
    slides = what_changed.reveal_slides(doc)
    renderer = what_changed.DeckRenderer(
        deck_review,
        str(tmp_path / "old"),
        str(tmp_path / "new"),
        str(tmp_path / "new/what-changed-decks"),
        "what-changed-decks",
    )
    assert renderer.review("deck.html", "deck.html", slides, slides, {0: 0}) is None


def test_marked_slide_phrase_is_one_mark():
    old = "<p>the <b>old</b> query token</p>"
    new = "<p>the <b>old</b> query, so every <b>new</b> token</p>"
    deleted, inserted = deck_review.word_changes(old, new)
    marked = deck_review.mark_words(new, inserted, "ins")
    assert marked == (
        '<p>the <b>old</b> <ins class="dr-live">query, so every</ins> '
        '<b><ins class="dr-live">new</ins></b> token</p>'
    )
    replaced = deck_review.mark_words(
        "<p>a x y z b</p>", {1, 2, 3}, "ins", {1: ["p", "q"]}
    )
    assert replaced == (
        '<p>a <del class="dr-live">p q</del> <ins class="dr-live">x y z</ins> b</p>'
    )


def test_marked_slide_strikes_deletions_where_they_were():
    struck = deck_review.struck_before("<p>a b c d</p>", "<p>a c d e</p>")
    assert struck == {1: ["b"]}
    assert deck_review.mark_words("<p>a c d e</p>", {3}, "ins", struck) == (
        '<p>a <del class="dr-live">b</del> c d <ins class="dr-live">e</ins></p>'
    )
    tail = deck_review.struck_before("<p>a b</p>", "<p>a</p>")
    assert deck_review.mark_words("<p>a</p>", set(), "ins", tail) == (
        '<p>a<del class="dr-live">b</del> </p>'
    )


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
    body, *_ = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {0: 0, 1: 1}, files, "b", "a"
    )
    assert "1 changed or new; 0 removed; 2 slides" in body
    assert "⋯ 1 unchanged slide (1)" in body
    assert "changed in look" not in body


def test_live_frames_open_the_deck_full_page_not_embedded(tmp_path):
    old_doc = _deck(['<section id="one"><h2>One</h2></section>'])
    new_doc = _deck(['<section id="one"><h2>Uno</h2></section>'])
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    body, *_ = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {0: 0}, files, "b", "a"
    )
    # A frame is the slide's own document, opened full page at its slide.
    assert (
        'data-src="a.frame-marked-1?view=slide&amp;scrollActivationWidth=0&amp;fragments=false'
        in body
        and "embedded" not in body
    )
    # Reveal's own floor on a slide's scale (.2) would cut a slide off in a frame
    # narrower than a fifth of its width: the frame lifts it.
    assert "&amp;minScale=0.05" in body


def test_live_frames_open_at_their_own_slide(tmp_path):
    """Narrow frames retain slide mode and navigate only by the slide ID hash."""
    old_doc = _deck(
        [
            '<section id="one"><h2>One</h2></section>',
            '<section id="two"><h2>Two</h2></section>',
        ]
    )
    new_doc = _deck(['<section id="one"><h2>One</h2></section>', EDITED])
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    body, old_marked, new_marked, *_ = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {0: 0, 1: 1}, files, "b", "a"
    )
    assert 'data-dr-slide-id="two"' in body
    assert "#/two" in body and "keyboard=false" in body
    assert "dr-slide=" not in body
    for doc in (old_marked, new_marked):
        assert "function hook()" not in doc
        assert "Reveal.slide(" not in doc


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
    body, *_ = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {1: 0, 2: 1}, files, "b", "a"
    )
    assert "1 changed or new; 0 removed; 3 slides" in body
    assert "changed in look" not in body


def _static_files(tmp_path, old_doc, new_doc, files=None, new_files=None):
    for side, doc, extra in (("old", old_doc, files), ("new", new_doc, new_files)):
        root = tmp_path / side
        (root / "d").mkdir(parents=True)
        (root / "d/deck.html").write_text(doc)
        for name, data in {
            "d/deck.css": "h2{}",
            "d/a.png": "A",
            **(files or {}),
            **(extra or {}),
        }.items():
            (root / name).write_text(data)
    return (
        deck_review.StaticFiles(str(tmp_path / "old"), str(tmp_path / "new")),
        what_changed.reveal_slides(old_doc),
        what_changed.reveal_slides(new_doc),
    )


def test_the_decks_own_bar_is_drawn_unless_the_page_has_its_own_control(tmp_path):
    doc = _deck([SLIDE])
    edited = doc.replace("One", "Uno")
    files, old, new = _static_files(tmp_path, doc, edited)
    args = ("d/deck.html", doc, edited, old, new, {0: 0}, files, "b", "a")
    body, *_ = deck_review.live_review(*args)
    for view in ("Changes marked", "Clean", "Before / after"):
        assert f">{view}</button>" in body
    assert 'class="dr-count"' in body
    bare, *_ = deck_review.live_review(*args, bar=False)
    assert "dr-bar" not in bare and "dr-seg" not in bare and "dr-count" not in bare
    # Either way the page's own control can set the view.
    assert "root.wcView = setView" in deck_review.LIVE_SCRIPT


def test_live_review_has_no_screenshot_implementation():
    assert not hasattr(deck_review, "Renderer")
    assert not hasattr(deck_review, "_serve")
    assert not hasattr(deck_review, "view")
    source = Path(deck_review.__file__).read_text()
    assert "playwright" not in source
    assert "screenshot(" not in source


def test_changed_section_background_is_changed_in_look(tmp_path):
    old_doc = _deck(
        [SLIDE.replace("<section ", '<section data-background-image="a.png" ')]
    )
    new_doc = _deck(
        [SLIDE.replace("<section ", '<section data-background-image="b.png" ')]
    )
    renderer, old, new = _static_files(tmp_path, old_doc, new_doc, {"d/b.png": "B"})
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
        "live",  # content whose pixels can change on their own
    ],
)
def test_differing_static_input_is_changed_in_look(tmp_path, change):
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
    new_doc = _deck(new_slides, head)
    renderer, old, new = _static_files(tmp_path, old_doc, new_doc, new_files=new_files)
    assert not renderer.same_static("d/deck.html", old[0], new[0])


@pytest.mark.parametrize(
    "prefix", ["\r", "\v", "\f", "\x1c", "\x85", "\u2028", "\u2029"]
)
def test_slide_spans_use_htmlparser_newlines(prefix):
    doc = _deck([SLIDE, EDITED], head=prefix + "\n<title>Deck</title>")
    slides = what_changed.reveal_slides(doc)
    for slide in slides:
        start, end = slide["span"]
        assert doc[start:end] == slide["raw"]
    marked = deck_review.marked_deck(doc, slides, {1: {0}}, "ins")
    assert '<section id="two"><h2><ins class="dr-live">Two</ins></h2>' in marked


def test_slide_parser_accepts_incremental_chunks():
    doc = _deck([SLIDE, EDITED], head="\n<title>Deck</title>\n")
    parser = what_changed.SlideParser()
    for start in range(0, len(doc), 7):
        parser.feed(doc[start : start + 7])
    parser.close()
    assert parser.slides() == what_changed.reveal_slides(doc)


@pytest.mark.parametrize(
    "protected",
    [
        '<aside class="notes"><p>secret old notes</p></aside>',
        "<svg><text>old vector text</text></svg>",
        "<math><mi>old</mi></math>",
        "<textarea>old input</textarea>",
        "<pre><code>old code</code></pre>",
        r"<p>\(old + x\)</p>",
        r"<p>\[old + x\]</p>",
        "<p>$old + x$</p>",
        "<p>$$old + x$$</p>",
    ],
)
def test_marks_preserve_non_prose_markup(protected):
    old = "<section><p>old prose</p>" + protected + "</section>"
    new = "<section><p>new prose</p>" + protected.replace("old", "new") + "</section>"
    deleted, inserted = deck_review.word_changes(old, new)
    marked = deck_review.mark_words(
        new, inserted, "ins", deck_review.struck_before(old, new)
    )
    assert protected.replace("old", "new") in marked
    assert '<ins class="dr-live">new</ins>' in marked
    assert '<del class="dr-live">old</del>' in marked


def test_live_notes_only_edit_is_unchanged(tmp_path):
    old_doc = _deck(
        [SLIDE.replace("</section>", '<aside class="notes">old</aside></section>')]
    )
    new_doc = old_doc.replace(">old<", ">new<")
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    rows, removed = deck_review.live_rows(
        old, new, {0: 0}, lambda a, b: files.same_static("d/deck.html", a, b)
    )
    assert rows == [("unchanged", 0, 0)] and not removed


@pytest.mark.parametrize("failure", ["decode", "copy", "parser"])
def test_live_deck_failure_falls_back_per_deck(tmp_path, monkeypatch, capsys, failure):
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    doc = _deck([SLIDE])
    (before / "deck.html").write_text(doc)
    (after / "deck.html").write_bytes(
        b"\xff" if failure == "decode" else doc.replace("One", "New").encode()
    )
    renderer = what_changed.DeckRenderer(
        deck_review, str(before), str(after), str(after / "generated"), "generated"
    )
    if failure == "copy":

        def fail(*a, **k):
            raise OSError("test copy failure")

        monkeypatch.setattr(what_changed.shutil, "copytree", fail)
    elif failure == "parser":

        def fail(*a, **k):
            raise ValueError("test parser failure")

        monkeypatch.setattr(deck_review, "live_review", fail)
    slides = what_changed.reveal_slides(doc)
    assert (
        renderer.review(
            "deck.html",
            "deck.html",
            slides,
            what_changed.reveal_slides(doc.replace("One", "New")),
            {0: 0},
        )
        is False
    )
    assert "slides as text" in capsys.readouterr().err


def test_live_deck_publication_skips_escaping_links(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "private.txt").write_text("must stay private")
    for root, word in [(before, "Old"), (after, "New")]:
        (root / "deck.html").write_text(
            _deck([f'<section id="s"><h2>{word}</h2></section>'])
        )
        (root / "escape").symlink_to(outside, target_is_directory=True)
        (root / "escape.txt").symlink_to(outside / "private.txt")
        (root / "local.css").write_text("h2{}")
        (root / "inside.css").symlink_to("local.css")
    renderer = what_changed.DeckRenderer(
        deck_review, str(before), str(after), str(after / "generated"), "generated"
    )
    old = what_changed.reveal_slides((before / "deck.html").read_text())
    new = what_changed.reveal_slides((after / "deck.html").read_text())
    assert renderer.review("deck.html", "deck.html", old, new, {0: 0})
    for side in ["before", "after"]:
        out = after / "generated" / side
        assert not (out / "escape").exists()
        assert not (out / "escape.txt").exists()
        assert (out / "inside.css").read_text() == "h2{}"
        assert "must stay private" not in "".join(
            p.read_text() for p in out.rglob("*") if p.is_file()
        )


def test_page_scan_excludes_html_symlink_outside_site(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    private = tmp_path / "private.html"
    private.write_text("<main>private content</main>")
    (site / "leak.html").symlink_to(private)
    assert what_changed.list_pages(str(site)) == {}
    renderer = what_changed.DeckRenderer(
        deck_review, str(site), str(site), str(site / "generated"), "generated"
    )
    assert renderer.review("leak.html", "leak.html", [], [], {}) is False


@pytest.mark.parametrize(
    "classes", ["notes-preview", "speaker-notes", "my-notes-extra"]
)
def test_visible_asides_do_not_count_as_speaker_notes(classes):
    raw = f'<aside class="{classes}">visible prose</aside>'
    assert deck_review.slide_words(raw) == ["visible", "prose"]


def test_invalid_deck_encoding_keeps_other_page_diffs(tmp_path, capsys):
    before, after = tmp_path / "before", tmp_path / "after"
    for root, word in [(before, "Old"), (after, "New")]:
        root.mkdir()
        (root / "index.html").write_text(f"<main><p>{word} prose</p></main>")
        doc = _deck(
            [f'<section id="s"><h2>{word}</h2></section>'],
            head="<!--" + " " * 5000 + "-->",
        )
        (root / "deck.html").write_bytes(
            doc.replace(word, word + ("\ufffd" if root == after else ""))
            .encode()
            .replace(b"\xef\xbf\xbd", b"\xff")
        )
    assert "deck.html" in what_changed.list_pages(str(after))
    out = after / "what-changed.html"
    what_changed.main(
        [
            "--old",
            str(before),
            "--new",
            str(after),
            "--out",
            str(out),
            "--render-decks",
            str(after / "generated"),
        ]
    )
    result = out.read_text()
    assert "slides as text" in capsys.readouterr().err
    assert "slide-diff" in result and "New" in result and "prose" in result


def test_marks_preserve_nested_svg_and_entity_words():
    old = "<section><p>old &amp; plain</p><svg><svg><text>inner old</text></svg><text>outer old</text></svg></section>"
    new = old.replace("old", "new")
    deleted, inserted = deck_review.word_changes(old, new)
    marked = deck_review.mark_words(
        new, inserted, "ins", deck_review.struck_before(old, new)
    )
    assert (
        "<svg><svg><text>inner new</text></svg><text>outer new</text></svg>" in marked
    )
    assert (
        '<del class="dr-live">old</del> <ins class="dr-live">new</ins> &amp; plain'
        in marked
    )


def test_nested_speaker_notes_do_not_change_visible_slide(tmp_path):
    old_doc = _deck(
        [
            SLIDE.replace(
                "</section>",
                '<aside class="notes"><aside>nested old</aside>old tail</aside></section>',
            )
        ]
    )
    new_doc = old_doc.replace("old", "new")
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    rows, _ = deck_review.live_rows(
        old, new, {0: 0}, lambda a, b: files.same_static("d/deck.html", a, b)
    )
    assert rows == [("unchanged", 0, 0)]


def test_before_after_frames_the_old_slide_red_and_the_new_slide_green(tmp_path):
    old_doc = _deck(['<section id="one"><h2>One</h2><p>old</p></section>'])
    new_doc = _deck(['<section id="one"><h2>One</h2><p>new</p></section>'])
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    body, *_ = deck_review.live_review(
        "d/deck.html", old_doc, new_doc, old, new, {0: 0}, files, "b", "a"
    )
    assert re.search(
        r'<figure data-view="before" class="dr-old"><figcaption>Before</figcaption>',
        body,
    )
    assert re.search(
        r'<figure data-view="before" class="dr-new"><figcaption>After</figcaption>',
        body,
    )
    # the frames of Changes marked and Clean carry no role
    assert '<figure data-view="marked"><figcaption>Changes marked' in body
    style = deck_review.LIVE_STYLE
    # thin red and green frames and labels in the page's own palette
    assert "figure.dr-old iframe{border-color:var(--wc-del-line" in style
    assert "figure.dr-new iframe{border-color:var(--wc-ins-line" in style
    assert "figure.dr-old figcaption{color:var(--wc-del-line" in style
    assert "figure.dr-new figcaption{color:var(--wc-ins-line" in style
    # Before / after sets old beside new, and old above new when the deck itself is
    # too narrow for two readable frames, whatever page holds it.
    assert (
        "[data-view=before] .dr-pair{grid-template-columns:repeat(2,minmax(0,1fr))}"
        in style
    )
    assert ".deck-live{container:deck-live / inline-size}" in style
    assert (
        "@container deck-live (max-width: 649px)"
        "{.deck-live[data-view=before] .dr-pair{grid-template-columns:minmax(0,1fr)}}"
        in style
    )
    # and each slide is fitted again by Reveal's own message, not by reaching in
    script = deck_review.LIVE_SCRIPT
    assert """postMessage('{"method":"layout"}', '*')""" in script
    assert "contentWindow.Reveal" not in script


def test_a_run_of_unchanged_slides_is_one_strip_named_in_slides(tmp_path):
    slides = [
        f'<section id="s{i}"><h2>S{i}</h2><p>same</p></section>' for i in range(4)
    ]
    old_doc = _deck([*slides, '<section id="e"><h2>E</h2><p>old</p></section>'])
    new_doc = _deck([*slides, '<section id="e"><h2>E</h2><p>new</p></section>'])
    files, old, new = _static_files(tmp_path, old_doc, new_doc)
    body, *_ = deck_review.live_review(
        "d/deck.html",
        old_doc,
        new_doc,
        old,
        new,
        {i: i for i in range(5)},
        files,
        "b",
        "a",
    )
    assert "⋯ 4 unchanged slides (1–4)" in body
    assert "Expand" not in body
