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
extension = pathlib.Path("_extensions/evidence/version.txt").read_text()
required = pathlib.Path("required-extension.txt")
if required.exists():
    extension += pathlib.Path("_extensions", required.read_text().strip(), "version.txt").read_text()
paras = f"<p>{extension}</p>" + "".join(f"<p>{line}</p>" for line in open("index.qmd").read().splitlines())
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
    (project / "_extensions/evidence").mkdir(parents=True)
    (project / "_extensions/evidence/version.txt").write_text("Baseline extension.")
    git(
        project, "add", "Makefile", "workspace.mk", "scripts", ".gitignore", "index.qmd"
    )
    git(project, "add", "-f", "_extensions/evidence/version.txt")
    git(project, "commit", "-qm", "first")
    git(project, "checkout", "-qb", "draft")
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
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA committed branch paragraph.\n"
    )
    git(project, "add", "index.qmd")
    git(project, "commit", "-qm", "branch work")
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA committed branch paragraph.\nA newly drafted paragraph.\n"
    )

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "newly drafted paragraph" in page
    assert "committed branch paragraph" in page
    assert (
        f"Changes since {git(project, 'rev-parse', '--short', 'main').strip()}" in page
    )
    assert "<ins" in page
    assert (project / "_site/index.html").is_file()
    worktrees = git(project, "worktree", "list", "--porcelain")
    assert sum(line.startswith("worktree ") for line in worktrees.splitlines()) == 1


def test_explicit_base_and_missing_base(project: Path, tmp_path: Path) -> None:
    git(project, "tag", "last-read")
    git(project, "branch", "-qm", "main", "unconfigured-base")
    (project / "index.qmd").write_text("A revised finding.\n")
    result = make(project, tmp_path, "WHAT_CHANGED_BASE=last-read")
    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    # Word-level markup can separate "revised" from the unchanged "finding".
    assert "revised" in page and "<ins" in page

    result = make(project, tmp_path)
    assert result.returncode != 0
    assert "WHAT_CHANGED_BASE" in result.stderr


@pytest.mark.parametrize("branch", ["master", "trunk", "custom-default"])
def test_local_default_branch(project: Path, tmp_path: Path, branch: str) -> None:
    git(project, "branch", "-m", "main", branch)
    if branch == "custom-default":
        git(project, "config", "init.defaultBranch", branch)
    git(project, "commit", "--allow-empty", "-qm", "branch work")
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "newly drafted paragraph" in page
    assert (
        f"Changes since {git(project, 'rev-parse', '--short', branch).strip()}" in page
    )


@pytest.mark.parametrize("cached_head", [True, False])
def test_remote_default_branch(
    project: Path, tmp_path: Path, cached_head: bool
) -> None:
    git(project, "branch", "-m", "main", "published-default")
    remote = tmp_path / "remote.git"
    git(project, "clone", "--bare", str(project), str(remote))
    git(remote, "symbolic-ref", "HEAD", "refs/heads/published-default")
    git(project, "remote", "add", "origin", str(remote))
    git(project, "fetch", "-q", "origin")
    if cached_head:
        git(project, "remote", "set-head", "origin", "-a")
    else:
        git(project, "update-ref", "--no-deref", "-d", "refs/remotes/origin/HEAD")
    git(project, "branch", "-D", "published-default")
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "newly drafted paragraph" in page
    expected = git(project, "rev-parse", "--short", "origin/published-default").strip()
    assert f"Changes since {expected}" in page


def test_base_uses_its_own_render_rules(project: Path, tmp_path: Path) -> None:
    with (project / "Makefile").open("a") as f:
        f.write(
            "render: prepare-report\nprepare-report:\n\t@test -f required-extension.txt || printf evidence > required-extension.txt\n"
        )
    git(project, "add", "Makefile")
    git(project, "commit", "-qm", "prepare render inputs")
    git(project, "branch", "-f", "main")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert (
        "No rendered content changed"
        in (project / "_site/what-changed.html").read_text()
    )


def test_baseline_keeps_its_recorded_extension(project: Path, tmp_path: Path) -> None:
    (project / "_extensions/evidence/version.txt").write_text("Current extension.")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "Baseline" in page and "Current" in page
    assert "<ins" in page and "<del" in page


def test_baseline_does_not_borrow_ignored_extension(
    project: Path, tmp_path: Path
) -> None:
    (project / "required-extension.txt").write_text("custom")
    git(project, "add", "required-extension.txt")
    git(project, "commit", "-qm", "require a custom extension")
    git(project, "branch", "-f", "main")
    (project / "_extensions/custom").mkdir()
    (project / "_extensions/custom/version.txt").write_text(
        "Current ignored extension."
    )

    result = make(project, tmp_path)

    assert result.returncode != 0
    assert "base render failed" in result.stderr
    assert "_extensions/custom/version.txt" in result.stderr
    assert not (project / "_site/what-changed.html").exists()
    worktrees = git(project, "worktree", "list", "--porcelain")
    assert sum(line.startswith("worktree ") for line in worktrees.splitlines()) == 1
