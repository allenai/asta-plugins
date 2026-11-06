"""`make what-changed` writes a local What changed page into `_site/` before any PR."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).parent.parent / "plugins/asta-tools/skills/workspace/assets"

# Stands in for `quarto render`: wraps index.qmd lines in the <main> Quarto emits.
FAKE_QUARTO = """#!/usr/bin/env python3
import pathlib, sys
assert sys.argv[1:] == ["render"], sys.argv
paras = "".join(f"<p>{line}</p>" for line in open("index.qmd").read().splitlines())
pathlib.Path("_site").mkdir(exist_ok=True)
pathlib.Path("_site/index.html").write_text(
    f"<html><head><title>Report</title></head><body><main>{paras}</main></body></html>"
)
"""

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")


def git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / "report"
    project.mkdir()
    shutil.copy(ASSETS / "workspace.mk", project / "workspace.mk")
    (project / "Makefile").write_text("include workspace.mk\n")
    (project / "scripts").mkdir()
    shutil.copy(ASSETS / "what-changed.py", project / "scripts/what-changed.py")
    (project / ".gitignore").write_text("_site/\n_extensions/\n")
    (project / "index.qmd").write_text("The baseline finding holds.\n")
    git(project, "init", "-q", "-b", "main")
    git(project, "add", ".")
    git(project, "commit", "-qm", "first")
    git(project, "checkout", "-qb", "draft")
    # A symlinked extension is never refreshed, so the test needs no network.
    (project / "_extensions").mkdir()
    (project / "_extensions/evidence").symlink_to(ASSETS / "_extensions/evidence")
    return project


def make(project: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "quarto").write_text(FAKE_QUARTO)
    (bin_dir / "quarto").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0", *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )


def test_uncommitted_edit_is_shown_against_branch_base(
    project: Path, tmp_path: Path
) -> None:
    git(project, "commit", "--allow-empty", "-qm", "branch work")
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "newly drafted paragraph" in page
    assert "<ins" in page
    assert (project / "_site/index.html").is_file()
    worktrees = git(project, "worktree", "list", "--porcelain")
    assert sum(line.startswith("worktree ") for line in worktrees.splitlines()) == 1


def test_explicit_base_and_missing_base(project: Path, tmp_path: Path) -> None:
    git(project, "tag", "last-read")
    (project / "index.qmd").write_text("A revised finding.\n")
    assert make(project, tmp_path, "WHAT_CHANGED_BASE=last-read").returncode == 0
    assert "revised finding" in (project / "_site/what-changed.html").read_text()

    git(project, "branch", "-qm", "main", "trunk")
    result = make(project, tmp_path)
    assert result.returncode != 0
    assert "WHAT_CHANGED_BASE" in result.stderr
