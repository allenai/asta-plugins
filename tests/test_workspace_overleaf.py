"""Tests for `asta workspace overleaf pull|publish` against a local bare remote."""

import importlib
import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from asta.cli import cli

module = importlib.import_module("asta.commands.overleaf")
URL = "https://git.overleaf.com/1234567"


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
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    remote = tmp_path / "overleaf.git"
    real = module.git_bytes
    monkeypatch.setattr(
        module,
        "git_bytes",
        lambda *a, **k: real(*(str(remote) if x == URL else x for x in a), **k),
    )
    git(tmp_path, "init", "--bare", "-b", "master", str(remote))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", str(remote), str(seed))
    (seed / "main.tex").write_text("hello\n")
    (seed / "old.tex").write_text("old\n")
    (seed / "references.bib").write_text("@misc{overleaf}\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "init")
    git(seed, "push", "origin", "master")
    project = tmp_path / "project"
    project.mkdir()
    git(project, "init", "-b", "main")
    (project / "references.bib").write_text("@misc{root}\n")
    git(project, "add", ".")
    git(project, "commit", "-m", "init")
    return seed, project


def run(project, *args):
    return CliRunner().invoke(
        cli, ["workspace", "overleaf", *args, "--project", str(project)]
    )


def overleaf_edit(seed, name, text):
    git(seed, "pull", "-q", "origin", "master")
    if text is None:
        git(seed, "rm", "-q", name)
    else:
        (seed / name).write_text(text)
        git(seed, "add", name)
    git(seed, "commit", "-m", "edit")
    git(seed, "push", "-q", "origin", "master")


def commit_all(project):
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "sync")


def test_pull_copies_paper_but_not_bibliography(setup):
    seed, project = setup
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    paper = project / "paper"
    assert (paper / "main.tex").read_text() == "hello\n"
    assert not (paper / "references.bib").exists()
    assert "differs from the workspace root copy" in result.output
    config = json.loads((paper / "overleaf.json").read_text())
    assert config == {"url": URL, "base": git(seed, "rev-parse", "HEAD")}


def test_pull_applies_overleaf_deletions_and_keeps_workspace_files(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "latexmkrc").write_text("# workspace only\n")
    commit_all(project)
    overleaf_edit(seed, "old.tex", None)
    overleaf_edit(seed, "main.tex", "edited in overleaf\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert not (project / "paper" / "old.tex").exists()
    assert (project / "paper" / "latexmkrc").exists()
    assert (project / "paper" / "main.tex").read_text() == "edited in overleaf\n"


def test_pull_refuses_uncommitted_paper_changes(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper" / "main.tex").write_text("local\n")
    result = run(project, "pull")
    assert result.exit_code != 0
    assert "local changes" in result.output
    assert (project / "paper" / "main.tex").read_text() == "local\n"


def test_publish_pushes_committed_paper_and_root_bibliography(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "main.tex").write_text("reviewed\n")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    dry = run(project, "publish", "--dry-run")
    assert dry.exit_code == 0 and "nothing pushed" in dry.output
    assert git(seed, "ls-remote", "origin", "master") == before
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "reviewed\n"
    assert (seed / "references.bib").read_text() == "@misc{root}\n"
    assert not (seed / "overleaf.json").exists()
    config = json.loads((project / "paper" / "overleaf.json").read_text())
    assert config["base"] == git(seed, "rev-parse", "HEAD")


def test_publish_refuses_when_overleaf_moved(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "Overleaf has changed" in result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "collaborator edit\n"


def test_publish_requires_committed_bibliography(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "references.bib").write_text("@misc{draft}\n")
    result = run(project, "publish")
    assert result.exit_code != 0 and "local changes" in result.output


@pytest.mark.parametrize(
    "local,remote",
    [("workspace\n", "overleaf\n"), ("workspace\n", None), (None, "overleaf\n")],
)
def test_pull_refuses_conflicting_committed_edits_without_writes(setup, local, remote):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    target = project / "paper" / "main.tex"
    if local is None:
        target.unlink()
    else:
        target.write_text(local)
    commit_all(project)
    metadata = (project / "paper" / "overleaf.json").read_bytes()
    overleaf_edit(seed, "old.tex", "a non-conflicting remote edit\n")
    overleaf_edit(seed, "main.tex", remote)
    result = run(project, "pull")
    assert result.exit_code != 0, result.output
    assert "both changed: main.tex" in result.output
    assert (target.read_text() if target.exists() else None) == local
    assert (project / "paper" / "old.tex").read_text() == "old\n"
    assert (project / "paper" / "overleaf.json").read_bytes() == metadata
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("local", ["workspace\n", None])
def test_pull_preserves_committed_edits_when_remote_file_is_unchanged(setup, local):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    target = project / "paper" / "main.tex"
    if local is None:
        target.unlink()
    else:
        target.write_text(local)
    commit_all(project)
    overleaf_edit(seed, "old.tex", "overleaf\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (target.read_text() if target.exists() else None) == local
    assert (project / "paper" / "old.tex").read_text() == "overleaf\n"


def test_pull_accepts_identical_edits_on_both_sides(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "main.tex").write_text("same edit\n")
    commit_all(project)
    overleaf_edit(seed, "main.tex", "same edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper" / "main.tex").read_text() == "same edit\n"


def test_first_pull_refuses_collision_with_existing_committed_paper(setup):
    _, project = setup
    paper = project / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text("existing project paper\n")
    commit_all(project)
    result = run(project, "pull", URL)
    assert result.exit_code != 0 and "both changed" in result.output
    assert (paper / "main.tex").read_text() == "existing project paper\n"
    assert not (paper / "overleaf.json").exists()


@pytest.mark.parametrize("pattern", ["paper/", "*.tex", "paper/overleaf.json"])
def test_pull_refuses_ignored_imports_before_any_writes(setup, pattern):
    _, project = setup
    (project / ".gitignore").write_text(pattern + "\n")
    commit_all(project)
    result = run(project, "pull", URL)
    assert result.exit_code != 0, result.output
    assert "Ignore rules hide imported files" in result.output
    assert not (project / "paper").exists()
    assert not git(project, "status", "--porcelain", "--ignored", "paper")


def test_pull_respects_tracked_files_despite_later_ignore_rule(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / ".gitignore").write_text("paper/\n")
    commit_all(project)
    overleaf_edit(seed, "main.tex", "remote edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert "paper/main.tex" in git(project, "diff", "--name-only")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
@pytest.mark.parametrize("command", ["pull", "publish", "publish --dry-run"])
def test_sync_refuses_remote_symlinks_without_changing_either_copy(setup, command):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (seed / "linked.tex").symlink_to("main.tex")
    git(seed, "add", "linked.tex")
    git(seed, "commit", "-m", "symlink")
    git(seed, "push", "origin", "master")
    # Exercise publication's unsupported-entry guard with a matching recorded base.
    config = project / "paper" / "overleaf.json"
    config.write_text(json.dumps({"url": URL, "base": git(seed, "rev-parse", "HEAD")}))
    commit_all(project)
    remote_head = git(seed, "ls-remote", "origin", "master")
    result = run(project, *command.split())
    assert result.exit_code != 0, result.output
    assert "only regular files are supported" in result.output
    assert not git(project, "status", "--porcelain")
    assert git(seed, "ls-remote", "origin", "master") == remote_head
    assert (seed / "linked.tex").is_symlink()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_publish_refuses_workspace_symlink(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "linked.tex").symlink_to("main.tex")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code != 0 and "only regular files are supported" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_executable_mode_round_trip_and_remote_mode_change(setup):
    seed, project = setup
    (seed / "main.tex").chmod(0o755)
    git(seed, "add", "main.tex")
    git(seed, "commit", "-m", "executable")
    git(seed, "push", "origin", "master")
    assert run(project, "pull", URL).exit_code == 0
    assert (project / "paper" / "main.tex").stat().st_mode & 0o100
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    git(seed, "pull", "origin", "master")
    assert git(seed, "ls-tree", "HEAD", "main.tex").startswith("100755")
    commit_all(project)
    (seed / "main.tex").chmod(0o644)
    git(seed, "add", "main.tex")
    git(seed, "commit", "-m", "not executable")
    git(seed, "push", "origin", "master")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert not (project / "paper" / "main.tex").stat().st_mode & 0o111


def test_publish_keeps_tracked_files_matching_paper_gitignore(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper" / ".gitignore").write_text("*.tex\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "origin", "master")
    assert git(seed, "show", "HEAD:main.tex") == "hello"


def test_pull_refuses_incoming_ignore_rules_before_any_writes(setup):
    seed, project = setup
    overleaf_edit(seed, ".gitignore", "*.tex\n")
    result = run(project, "pull", URL)
    assert result.exit_code != 0 and "Ignore rules hide imported files" in result.output
    assert not (project / "paper").exists()


@pytest.mark.parametrize(
    "url", ["https://example.com/x", "https://git:pw@git.overleaf.com/1", "", None]
)
def test_rejects_non_overleaf_urls(setup, url):
    _, project = setup
    result = run(project, "pull", *([url] if url is not None else []))
    assert result.exit_code != 0
    assert "git.overleaf.com/<project-id>" in result.output


@pytest.mark.skipif(os.name == "nt", reason="POSIX askpass")
def test_token_uses_askpass_and_disables_helpers(monkeypatch):
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    with module.credentials() as (env, options):
        askpass = env["GIT_ASKPASS"]
        assert options == ["-c", "credential.helper="]
        answer = subprocess.run(
            [askpass, "Password for x"], env=env, capture_output=True, text=True
        )
        assert answer.stdout.strip() == "fixture-token"
        assert "fixture-token" not in open(askpass).read()
    assert not os.path.exists(askpass)
