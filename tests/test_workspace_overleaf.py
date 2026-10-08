"""Tests for `asta workspace overleaf pull|publish` against a local bare remote."""

import json
import subprocess

import pytest
from click.testing import CliRunner

from asta.cli import cli


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv("OVERLEAF_TOKEN", raising=False)
    remote = tmp_path / "overleaf.git"
    git(tmp_path, "init", "--bare", "-b", "master", str(remote))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", str(remote), str(seed))
    (seed / "main.tex").write_text("hello\n")
    (seed / "old.tex").write_text("old\n")
    (seed / "references.bib").write_text("@misc{a}\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "init")
    git(seed, "push", "origin", "master")
    project = tmp_path / "project"
    project.mkdir()
    git(project, "init", "-b", "main")
    (project / ".gitignore").write_text(".asta/cache/\n")
    (project / "references.bib").write_text("@misc{a}\n")
    git(project, "add", ".")
    git(project, "commit", "-m", "init")
    return remote, seed, project


def run(project, *args):
    return CliRunner().invoke(
        cli, ["workspace", "overleaf", *args, "--project", str(project)]
    )


def overleaf_edit(seed, name, text, message="edit"):
    git(seed, "pull", "origin", "master")
    (seed / name).write_text(text)
    git(seed, "add", ".")
    git(seed, "commit", "-m", message)
    git(seed, "push", "origin", "master")


def test_pull_imports_without_shared_bibliography(setup):
    remote, _, project = setup
    result = run(project, "pull", str(remote))
    assert result.exit_code == 0, result.output
    paper = project / "paper"
    assert (paper / "main.tex").read_text() == "hello\n"
    assert not (paper / "references.bib").exists()
    config = json.loads((paper / "overleaf.json").read_text())
    assert config["url"] == str(remote) and len(config["base"]) == 40


def test_publish_round_trip_and_refuses_unpulled_edits(setup):
    remote, seed, project = setup
    assert run(project, "pull", str(remote)).exit_code == 0
    (project / "paper" / "main.tex").write_text("reviewed\n")
    (project / "paper" / "old.tex").unlink()
    (project / "paper" / "latexmkrc").write_text("# workspace\n")
    git(project, "add", ".")
    git(project, "commit", "-m", "edit paper")

    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "origin", "master")
    assert (seed / "main.tex").read_text() == "reviewed\n"
    assert not (seed / "old.tex").exists()
    assert (seed / "references.bib").exists()
    assert not (seed / "overleaf.json").exists()
    assert "Asta-Workspace-Commit:" in git(seed, "log", "-1", "--format=%B")

    # Publishing again over our own commit is allowed (no new Overleaf edits).
    assert run(project, "publish").exit_code == 0

    overleaf_edit(seed, "main.tex", "coauthor edit\n")
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "Overleaf has edits" in result.output

    assert run(project, "pull").exit_code == 0
    assert (project / "paper" / "main.tex").read_text() == "coauthor edit\n"
    git(project, "add", ".")
    git(project, "commit", "-m", "pull overleaf")
    assert run(project, "publish").exit_code == 0


def test_pull_refuses_uncommitted_paper_edits(setup):
    remote, _, project = setup
    assert run(project, "pull", str(remote)).exit_code == 0
    git(project, "add", ".")
    git(project, "commit", "-m", "import")
    (project / "paper" / "main.tex").write_text("local\n")
    result = run(project, "pull")
    assert result.exit_code != 0
    assert "uncommitted changes" in result.output


def test_pull_removes_files_deleted_in_overleaf(setup):
    remote, seed, project = setup
    assert run(project, "pull", str(remote)).exit_code == 0
    git(project, "add", ".")
    git(project, "commit", "-m", "import")
    git(seed, "pull", "origin", "master")
    git(seed, "rm", "-q", "old.tex")
    git(seed, "commit", "-m", "rm")
    git(seed, "push", "origin", "master")
    assert run(project, "pull").exit_code == 0
    assert not (project / "paper" / "old.tex").exists()


def test_publish_dry_run_pushes_nothing(setup):
    remote, seed, project = setup
    assert run(project, "pull", str(remote)).exit_code == 0
    (project / "paper" / "main.tex").write_text("draft\n")
    git(project, "add", ".")
    git(project, "commit", "-m", "edit")
    result = run(project, "publish", "--dry-run")
    assert result.exit_code == 0 and "Dry run" in result.output
    git(seed, "pull", "origin", "master")
    assert (seed / "main.tex").read_text() == "hello\n"
