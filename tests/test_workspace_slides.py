"""Rendered deck review diffs and real Quarto website integration."""

import importlib.util
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ASSETS = (
    Path(__file__).resolve().parents[1] / "plugins/asta-tools/skills/workspace/assets"
)


def load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ASSETS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(project, *args):
    return subprocess.check_output(
        ["git", "-C", str(project), *args], text=True
    ).strip()


def deck(*slides):
    return (
        '<html><head><title>Talk</title></head><body><div class="reveal"><div class="slides">'
        + "".join(slides)
        + "</div></div></body></html>"
    )


def slide(ident, text):
    return f'<section id="{ident}" class="slide level2"><h2>{ident}</h2><p>{text}</p></section>'


def test_changed_deck_diffs_leaf_slides_and_links_to_preview(tmp_path):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    for root in [old, new]:
        (root / "slides/a").mkdir(parents=True)
    (old / "slides/a/slides.html").write_text(
        deck(
            '<section class="stack">'
            + slide("kept", "old finding")
            + slide("gone", "Removed content")
            + "</section>"
        )
    )
    (new / "slides/a/slides.html").write_text(
        deck(
            '<section class="stack">'
            + slide("kept", "new finding")
            + slide(
                "added",
                "Added content<script>alert(1)</script><img src=x onerror=alert(2)>",
            )
            + "</section>"
        )
    )
    (new / "index.html").write_text("<main><h1>Site</h1><p>New prose</p></main>")
    output = generator.build(str(old), str(new), "https://example.org/preview", "Test")
    assert output.index("Slides · Talk") < output.index("New prose")
    assert "slides.html#/kept" in output and "slides.html#/added" in output
    assert "slides.html#/gone" not in output
    assert "<del>old</del>" in output and "<ins>new</ins>" in output
    assert "Removed" in output and "Added" in output and "content" in output
    assert "alert(1)" not in output and "onerror" not in output
    assert output.count('class="slide-diff changed"') == 2


def test_unchanged_deck_does_not_diff_embedded_libraries(tmp_path):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    for root, script in [(old, "old library"), (new, "new library")]:
        (root / "slides.html").write_text(
            deck(slide("a", "Same content")) + f"<script>{script}</script>"
        )
    output = generator.build(str(old), str(new), "", "Test")
    assert "No rendered content changed" in output
    assert "new library" not in output


@pytest.mark.parametrize("removed", [False, True])
def test_added_and_removed_decks_have_one_review_section(tmp_path, removed):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    target = old if removed else new
    (target / "slides.html").write_text(deck(slide("a", "Talk content")))
    output = generator.build(str(old), str(new), "", "Test")
    assert output.count('class="slide-diff ') == 1
    assert "Talk content" in output
    assert ('href="slides.html#/a"' in output) is not removed


def test_inlined_links_are_rebased_to_the_diff_page(tmp_path):
    # What changed sits at the site root, so links copied from a deck or page
    # in a subfolder must resolve from there, never above the site.
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (new / "slides/a").mkdir(parents=True)
    (new / "notes").mkdir()
    (new / "slides/a/slides.html").write_text(
        deck(
            '<section id="s" class="slide level2"><h2>s</h2>'
            '<p><a href="../../lit-review/index.html#top">Review</a>'
            '<img src="figure.png" alt="f"><a href="#local">here</a>'
            '<a href="https://example.org/x">out</a></p></section>'
        )
    )
    (new / "notes/page.html").write_text(
        '<main><p><a href="../paper/html/index.html">Paper</a>'
        '<a href="/root.html">root</a><a href="../../outside.html">up</a></p></main>'
    )
    output = generator.build(str(old), str(new), "", "Test")
    assert 'href="lit-review/index.html#top"' in output
    assert 'src="slides/a/figure.png"' in output
    assert 'href="#local"' in output and 'href="https://example.org/x"' in output
    assert 'href="paper/html/index.html"' in output
    assert 'href="/root.html"' in output and 'href="../../outside.html"' in output
    assert 'href="../../lit-review' not in output


@pytest.mark.skipif(not shutil.which("quarto"), reason="requires Quarto")
def test_quarto_builds_and_auto_links_multiple_nested_decks(tmp_path):
    shutil.copytree(
        ASSETS / "_extensions/asta-slides", tmp_path / "_extensions/asta-slides"
    )
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: website\nwebsite:\n  title: Site\n  sidebar:\n    contents: auto\nformat: html\n"
    )
    (tmp_path / "index.qmd").write_text("---\ntitle: Home\n---\n\nWorkspace.\n")
    for name in ["slides/a", "slides/nested/b"]:
        folder = tmp_path / name
        folder.mkdir(parents=True)
        (folder / "slides.qmd").write_text(
            "---\ntitle: A talk\nformat: asta-slides-revealjs\n---\n\n# Section\n\n## Content\n\nText.\n"
        )
    result = subprocess.run(
        ["quarto", "render"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "[WARNING]" not in result.stderr and "WARN:" not in result.stderr
    index = (tmp_path / "_site/index.html").read_text()
    for name in ["slides/a", "slides/nested/b"]:
        assert f"{name}/slides.html" in index
        rendered = (tmp_path / "_site" / name / "slides.html").read_text()
        assert "asta-slides-section-header" in rendered
        assert "data:font/woff2" in rendered or "data:application/font-woff" in rendered


@pytest.mark.skipif(not shutil.which("make"), reason="requires make")
@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
@pytest.mark.parametrize("filename", ["slides.qmd", "custom-name.qmd"])
def test_workspace_fetches_slides_from_selected_ref_and_preserves_ejected_copy(
    tmp_path, rules, filename
):
    source = tmp_path / "release/plugins/asta-tools/skills/workspace/assets/_extensions"
    for name in ["evidence", "asta-slides"]:
        shutil.copytree(ASSETS / "_extensions" / name, source / name)
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source.parents[5], arcname="release")
    project = tmp_path / "project"
    (project / "slides/a").mkdir(parents=True)
    (project / "slides/a" / filename).write_text("format: asta-slides-revealjs\n")
    git(project, "init", "-q")

    def install():
        subprocess.run(
            ["make", "-f", str(ASSETS / rules), "workspace-assets"],
            cwd=project,
            env={**os.environ, "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri()},
            check=True,
            capture_output=True,
        )

    install()
    extension = project / "_extensions/asta-slides/_extension.yml"
    assert "self-contained-math: true" in extension.read_text()
    extension.write_text(extension.read_text() + "# Ejected\n")
    git(project, "add", "_extensions/asta-slides/_extension.yml")
    install()
    assert extension.read_text().endswith("# Ejected\n")


@pytest.mark.skipif(not shutil.which("make"), reason="requires make")
@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
@pytest.mark.parametrize(
    ("deck", "needs_slides"),
    [("slides/build/slides.qmd", True), ("build/talk/slides.qmd", False)],
)
def test_workspace_skips_generated_directories_only_at_project_root(
    tmp_path, rules, deck, needs_slides
):
    source = tmp_path / "release/plugins/asta-tools/skills/workspace/assets/_extensions"
    for name in ["evidence", "asta-slides"]:
        shutil.copytree(ASSETS / "_extensions" / name, source / name)
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source.parents[5], arcname="release")
    project = tmp_path / "project"
    (project / deck).parent.mkdir(parents=True)
    (project / deck).write_text("format: asta-slides-revealjs\n")
    git(project, "init", "-q")

    subprocess.run(
        ["make", "-f", str(ASSETS / rules), "workspace-assets"],
        cwd=project,
        env={**os.environ, "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri()},
        check=True,
        capture_output=True,
    )

    assert (project / "_extensions/evidence").is_dir()
    assert (project / "_extensions/asta-slides").is_dir() == needs_slides


@pytest.mark.parametrize("classes", ["reveal-on-scroll", "quarto-reveal", "revealing"])
def test_ordinary_page_classes_do_not_turn_sections_into_slides(tmp_path, classes):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    for root, content in [(old, "Before"), (new, "After")]:
        root.mkdir()
        (root / "index.html").write_text(
            f'<main><div class="{classes}"><div class="slides"><section><p>{content}</p></section></div></div></main>'
        )
    output = generator.build(str(old), str(new), "", "Test")
    assert "Slides ·" not in output
    assert "<del>Before</del>" in output and "<ins>After</ins>" in output


@pytest.mark.parametrize("anonymous", [False, True])
@pytest.mark.parametrize("removed", [False, True])
def test_slide_insertions_and_removals_do_not_report_unchanged_following_slides(
    tmp_path, anonymous, removed
):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    kept = [
        slide("" if anonymous else name, text)
        for name, text in [("a", "Kept first"), ("b", "Kept last")]
    ]
    inserted = slide("" if anonymous else "inserted", "Inserted finding")
    before, after = deck(*kept), deck(kept[0], inserted, kept[1])
    if removed:
        before, after = after, before
    (old / "slides.html").write_text(before)
    (new / "slides.html").write_text(after)
    output = generator.build(str(old), str(new), "", "Test")
    assert output.count('class="slide-diff ') == 1
    assert "Inserted finding" in output
    assert "Kept last" not in output


def test_pure_slide_reordering_has_one_note_without_repeating_content():
    generator = load("what-changed")
    output, _ = generator.slide_diff(
        deck(slide("a", "A"), slide("b", "B")),
        deck(slide("b", "B"), slide("a", "A")),
        "slides.html",
        "slides.html",
    )
    assert output.count("Slides reordered") == 1
    assert 'class="slide-diff ' not in output


@pytest.mark.parametrize("open_tag", ["p", "div", "em"])
def test_unclosed_slide_content_and_stray_end_tags_do_not_swallow_later_slides(
    open_tag,
):
    generator = load("what-changed")
    doc = (
        deck(
            f'<section id="first"><{open_tag}>First</section></p>',
            slide("second", "Second content"),
        )
        + '<div class="slides"><section>Outside Reveal</section></div>'
    )
    slides = generator.reveal_slides(doc)
    assert [slide["id"] for slide in slides] == ["first", "second"]
    assert "Second content" in slides[1]["body"]
    output, _ = generator.slide_diff(None, doc, "slides.html", "slides.html")
    assert 'href="slides.html#/second"' in output


def test_retitled_slide_is_changed_even_when_quarto_changes_its_id():
    generator = load("what-changed")
    output, _ = generator.slide_diff(
        deck(slide("old-title", "Same finding"), slide("kept", "Unchanged")),
        deck(slide("new-title", "Same finding"), slide("kept", "Unchanged")),
        "slides.html",
        "slides.html",
    )
    assert output.count('class="slide-diff changed"') == 1
    assert 'class="slide-diff new"' not in output
    assert 'class="slide-diff removed"' not in output
    assert 'href="slides.html#/new-title"' in output


def test_duplicate_title_insertion_matches_unchanged_bodies_before_shifted_ids():
    generator = load("what-changed")

    def titled(ident, content):
        return f'<section id="{ident}"><h2>Results</h2><p>{content}</p></section>'

    old = deck(
        titled("results", "First finding"), titled("results-1", "Second finding")
    )
    new = deck(
        titled("results", "Inserted finding"),
        titled("results-1", "First finding"),
        titled("results-2", "Second finding"),
    )
    output, _ = generator.slide_diff(old, new, "slides.html", "slides.html")
    assert output.count('class="slide-diff new"') == 1
    assert 'class="slide-diff changed"' not in output
    assert "First finding" not in output and "Second finding" not in output


@pytest.mark.parametrize("removed", [False, True])
def test_added_and_removed_slides_sanitize_active_html(removed):
    generator = load("what-changed")
    doc = deck(
        slide(
            "unsafe",
            '<iframe src="https://example.org">iframe payload</iframe>'
            '<object data="https://example.org">object payload</object>'
            '<style>style payload</style><a href="javascript:alert(1)">Safe label</a>',
        )
    )
    output, _ = generator.slide_diff(
        doc if removed else None, None if removed else doc, "slides.html", "slides.html"
    )
    assert "Safe label" in output
    for forbidden in (
        "<iframe",
        "<object",
        "<style",
        "javascript:",
        "iframe payload",
        "object payload",
        "style payload",
    ):
        assert forbidden not in output


def test_nested_content_sections_stay_in_the_slide_and_vertical_hashes_work():
    generator = load("what-changed")
    doc = deck(
        slide("intro", "Text<section><p>Nested content</p></section>"),
        "<section><section><p>First vertical</p></section><section><p>Second vertical</p></section></section>",
    )
    slides = generator.reveal_slides(doc)
    assert len(slides) == 3
    assert "Nested content" in slides[0]["body"]
    output, _ = generator.slide_diff(None, doc, "slides.html", "slides.html")
    assert 'href="slides.html#/1/0"' in output
    assert 'href="slides.html#/1/1"' in output
    assert "Nested content" in output


@pytest.mark.parametrize("to_deck", [False, True])
def test_format_transitions_retain_both_versions_in_the_page_diff(tmp_path, to_deck):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    before, after = (
        "<main><p>Ordinary page</p></main>",
        deck(slide("a", "Slide content")),
    )
    if not to_deck:
        before, after = after, before
    (old / "talk.html").write_text(before)
    (new / "talk.html").write_text(after)
    output = generator.build(str(old), str(new), "", "Test")
    assert all(word in output for word in ("Ordinary", "page", "Slide", "content"))
    assert "<ins>" in output and "<del>" in output
    assert "Slides ·" not in output


def test_embedded_slide_images_do_not_inflate_the_diff():
    generator = load("what-changed")
    image = '<img alt="A plot" src="data:image/png;base64,' + "A" * 100_000 + '">'
    output, _ = generator.slide_diff(
        None, deck(slide("a", image)), "slides.html", "slides.html"
    )
    assert "data:image" not in output
    assert len(output) < 2000
    assert "A plot" in output


def _site_with_deck(root, render, body):
    shutil.copytree(
        ASSETS / "_extensions/asta-slides",
        root / "_extensions/asta-slides",
        dirs_exist_ok=True,
    )
    (root / "_quarto.yml").write_text(
        f"project:\n  type: website\n{render}format: html\n"
    )
    (root / "index.qmd").write_text("---\ntitle: Home\n---\n\nWorkspace.\n")
    deck = root / "slides/workspace"
    deck.mkdir(parents=True, exist_ok=True)
    (deck / "slides.qmd").write_text(
        "---\ntitle: A talk\nformat: asta-slides-revealjs\nasta-slides:\n  section-slides: false\n---\n\n"
        + body
    )
    return deck


DECK = "## Opening\n\nOwn title.\n\n# First\n\n## One\n\nText.\n\n# Second\n\n## Two\n\n{}\n"


@pytest.mark.skipif(not shutil.which("quarto"), reason="requires Quarto")
@pytest.mark.parametrize(
    "command", [["render"], ["render", "slides/workspace/slides.qmd"]]
)
def test_deck_two_folders_down_finds_site_extension(tmp_path, command):
    _site_with_deck(
        tmp_path,
        '  render:\n    - index.qmd\n    - "slides/**/slides.qmd"\n',
        DECK.format("Text."),
    )
    result = subprocess.run(
        ["quarto", *command], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "_site/slides/workspace/slides.html").exists()


@pytest.mark.skipif(not shutil.which("quarto"), reason="requires Quarto")
def test_section_slides_false_drops_dividers_and_what_changed_numbers_as_deck(tmp_path):
    rendered = []
    for text in ["Before.", "After."]:
        _site_with_deck(tmp_path, "", DECK.format(text))
        subprocess.run(
            ["quarto", "render", "slides/workspace/slides.qmd"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        rendered.append((tmp_path / "_site/slides/workspace/slides.html").read_text())
    generator = load("what-changed")
    slides = generator.reveal_slides(rendered[1])
    assert len(slides) == 4  # title, opening, One, Two: no divider slides
    assert 'data-asta-section-name="Second"' in rendered[1]
    assert "<h1" not in "".join(slide["body"] for slide in slides[1:])
    output, _ = generator.slide_diff(*rendered, "slides.html", "slides.html")
    assert "Slide 4: Two" in output
