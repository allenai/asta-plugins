"""Dependency edits must include all affected pages in either revision."""

import pytest

from asta.commands.workspace_selection import select_pages


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
            "result",
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
