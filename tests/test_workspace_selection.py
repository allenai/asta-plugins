"""Dependency edits must include all affected pages in either revision."""

import shutil
from pathlib import Path

import pytest

from asta.commands.workspace_selection import paper_affected, select_pages


@pytest.fixture
def trees(tmp_path):
    roots = [tmp_path / side for side in ("before", "after")]
    for root in roots:
        root.mkdir()

    def write(name, old, new=None):
        for root, text in zip(roots, (old, old if new is None else new)):
            if text is not None:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)

    return roots, write


@pytest.mark.parametrize(
    "name,old,new,reference",
    [
        (
            "evidence.yml",
            "evidence:\n  result: {quote: old}",
            "evidence:\n  result: {quote: new}",
            '[x]{.ev key="result"}',
        ),
        (
            "references.bib",
            "@article{key, title={Old}}",
            "@article{key, title={New}}",
            "@key",
        ),
        ("plot.svg", "old", "new", "images/../plot.svg"),
        ("data.csv", "old", "new", "data.csv"),
        ("include.qmd", "old", "new", "{{< include include.qmd >}}"),
        ("_include.qmd", "old", "new", "{{< include _include.qmd >}}"),
    ],
)
def test_dependencies_followed_through_include(trees, name, old, new, reference):
    (before, after), write = trees
    write(name, old, new)
    write("_middle.qmd", reference)
    write("page.qmd", "{{< include _middle.qmd >}}")
    write("unrelated.qmd", "unrelated")
    selected = select_pages(after, before, [name])
    assert "page.qmd" in selected
    assert "unrelated.qmd" not in selected


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("_quarto.yml", "project: {}", "project: {type: website}"),
        ("evidence.yml", "evidence: {a: old}", "bad: ["),
        ("references.bib", "@article{key,title={old}}", "@article{key,title={new}"),
        ("evidence.yml", "evidence: {a: old}", "evidence: {a: old}\n# comment"),
        ("new.qmd", None, "new"),
        ("deleted.qmd", "old", None),
        ("script.py", "old", "new"),
    ],
)
def test_unknown_and_topology_changes_compare_everything(trees, name, old, new):
    (before, after), write = trees
    # Fixture's None default means 'same'; remove explicitly for deletion.
    write(name, old, new)
    if new is None:
        (after / name).unlink()
    write("page.qmd", "page")
    assert select_pages(after, before, [name]) is None


def test_old_reference_still_selects_page(trees):
    (before, after), write = trees
    write("image.svg", "old", "new")
    write("page.qmd", "image.svg", "no image")
    assert select_pages(after, before, ["image.svg"]) == ["page.qmd"]


def test_paper_dependency_filter(tmp_path):
    from asta.commands.workspace_selection import paper_affected

    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(r"\input{section}\bibliography{../shared}")
    (paper / "section.tex").write_text(r"\includegraphics{../figure}")
    assert not paper_affected(tmp_path, "paper", "main.tex", ["slides.qmd"])
    assert not paper_affected(tmp_path, "paper", "main.tex", ["unrelated.bib"])
    for name in ["shared.bib", "figure.png", "paper/section.tex", "Makefile"]:
        assert paper_affected(tmp_path, "paper", "main.tex", [name])
    (paper / "section.tex").write_text(r"\input{\generated}")
    assert paper_affected(tmp_path, "paper", "main.tex", ["slides.qmd"])


def test_extension_source_edit_with_deck_edit_still_compares_all(trees):
    (before, after), write = trees
    write("slides.qmd", "old", "new")
    write("_extensions/theme/template.qmd", "old", "new")
    assert (
        select_pages(after, before, ["slides.qmd", "_extensions/theme/template.qmd"])
        is None
    )


def test_bibliography_macros_with_entry_edit_compare_all(trees):
    (before, after), write = trees
    write(
        "references.bib",
        '@string{journal="old"}\n@article{key,title={old}}',
        '@string{journal="new"}\n@article{key,title={new}}',
    )
    write("page.qmd", "@key")
    assert select_pages(after, before, ["references.bib"]) is None


def test_links_and_mentions_are_not_includes(trees):
    (before, after), write = trees
    write("slides.qmd", "old", "new")
    write(
        "evidence.yml", "evidence:\n  q: {quote: old}", "evidence:\n  q: {quote: new}"
    )
    write("citing.qmd", '[claim]{.ev key="q"}')
    write("mentions.qmd", "See [the deck](slides.qmd); quote id `q`, slides.html.")
    write("including.qmd", "{{< include slides.qmd >}}")
    write("embedding.qmd", "{{< embed sub/../slides.qmd#fig >}}")
    assert select_pages(after, before, ["slides.qmd"]) == [
        "embedding.qmd",
        "including.qmd",
        "slides.qmd",
    ]
    assert select_pages(after, before, ["evidence.yml"]) == ["citing.qmd"]


def test_quote_id_mentioned_but_never_cited_compares_all(trees):
    (before, after), write = trees
    write(
        "evidence.yml", "evidence:\n  q: {quote: old}", "evidence:\n  q: {quote: new}"
    )
    write("page.qmd", "the id `q` is a quote")
    assert select_pages(after, before, ["evidence.yml"]) is None


def test_bibliography_entry_selects_pages_citing_it_directly_or_via_evidence(trees):
    (before, after), write = trees
    write("references.bib", "@article{k1, title={Old}}", "@article{k1, title={New}}")
    write("evidence.yml", "evidence:\n  q: {quote: x, cite: k1}")
    write("direct.qmd", "As shown [@k1, p. 2].")
    write("via-evidence.qmd", '[claim]{.ev key="q"}')
    write("nocite.qmd", "---\nnocite: '@*'\n---\n")
    write("other.qmd", "@k10 and k1 in prose")
    assert select_pages(after, before, ["references.bib"]) == [
        "direct.qmd",
        "nocite.qmd",
        "via-evidence.qmd",
    ]


def test_unresolvable_include_selects_its_page(trees):
    (before, after), write = trees
    write("slides.qmd", "old", "new")
    write("dynamic.qmd", "{{< include {{< meta part >}} >}}")
    assert "dynamic.qmd" in select_pages(after, before, ["slides.qmd"])


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "workspace"


@pytest.fixture
def example(tmp_path):
    roots = []
    for side in ("before", "after"):
        root = tmp_path / side
        shutil.copytree(
            EXAMPLE, root, ignore=shutil.ignore_patterns("_site", ".quarto", "_freeze")
        )
        roots.append(root)
    return roots


def _edit(root, name, old, new):
    path = root / name
    text = path.read_text()
    assert old in text, f"{old!r} not in {name}"
    path.write_text(text.replace(old, new, 1))


def test_example_slide_edit_renders_only_its_deck(example):
    """The example has a page linking to the deck; it must not be rendered."""
    before, after = example
    deck = "slides/attention/slides.qmd"
    assert deck in (after / "appearance.qmd").read_text()
    _edit(after, deck, "## ", "## Edited ")
    assert select_pages(after, before, [deck]) == [deck]
    assert not paper_affected(after, "paper", _paper_main(after), [deck])


def test_example_quote_edit_renders_only_pages_citing_it(example):
    """appearance.qmd mentions the quote id without citing it."""
    before, after = example
    assert "transformer-attention" in (after / "appearance.qmd").read_text()
    _edit(after, "evidence.yml", "quote: ", "quote: Edited ")
    assert select_pages(after, before, ["evidence.yml"]) == ["lit-review/index.qmd"]
    assert not paper_affected(after, "paper", _paper_main(after), ["evidence.yml"])


def _paper_main(root):
    return next(
        p.name
        for p in (root / "paper").glob("*.tex")
        if "documentclass" in p.read_text()
    )


def test_example_bibliography_edit_builds_paper(example):
    before, after = example
    main = _paper_main(after)
    assert paper_affected(after, "paper", main, ["paper/references.bib"])
    (after / "paper" / "latexmkrc").write_text("$pdf_mode = 1;\n")
    assert paper_affected(after, "paper", main, ["slides/attention/slides.qmd"])
