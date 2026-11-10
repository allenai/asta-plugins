"""Check the real-render matrix's edits and independent render expectations."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from asta.commands.workspace_selection import select_pages

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/browser"))
spec = importlib.util.spec_from_file_location(
    "differential", ROOT / "tests/browser/workspace-differential.py"
)
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


@pytest.mark.parametrize(
    "case",
    [
        "prose",
        "metadata",
        "slide",
        "quote",
        "bibliography",
        "config",
        "image",
        "new",
        "deleted",
        "renamed",
        "paper-bibliography",
        "paper",
        "include",
    ],
)
def test_edit_matrix_expected_selection(tmp_path, case):
    before, after = tmp_path / "before", tmp_path / "after"
    for directory in (before, after):
        shutil.copytree(ROOT / "examples/workspace", directory)
        (directory / "differential.svg").write_text('<svg fill="#008080"/>')
        with (directory / "appearance.qmd").open("a") as stream:
            stream.write("\n![Asset](differential.svg)\n")
    expected, _ = matrix.edit(after, case)
    changed = [
        p.relative_to(after).as_posix()
        for p in after.rglob("*")
        if p.is_file()
        and (
            not (before / p.relative_to(after)).is_file()
            or p.read_bytes() != (before / p.relative_to(after)).read_bytes()
        )
    ]
    changed += [
        p.relative_to(before).as_posix()
        for p in before.rglob("*")
        if p.is_file() and not (after / p.relative_to(before)).exists()
    ]
    selected = select_pages(after, before, changed)
    if selected is not None:
        assert set(selected) == expected - {matrix.LOOK}
    else:
        assert case in {
            "config",
            "metadata",
            "new",
            "deleted",
            "renamed",
            "paper-bibliography",
            "paper",
        }
