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


@pytest.mark.parametrize(
    ("name", "text", "reason"),
    [
        (".gitattributes", "*.tex filter=lfs\n", "change file contents"),
        (
            "fig.png",
            "version https://git-lfs.github.com/spec/v1\noid sha256:0\n",
            "LFS",
        ),
        ("MAIN.tex", "upper\n", "letter case"),
    ],
)
def test_pull_refuses_unsupported_files_before_writing(setup, name, text, reason):
    seed, project = setup
    overleaf_edit(seed, name, text)
    result = run(project, "pull", URL)
    assert result.exit_code != 0
    assert reason in result.output
    assert not (project / "paper").exists()


def test_pull_refuses_symlinks(setup):
    seed, project = setup
    os.symlink("main.tex", seed / "link.tex")
    git(seed, "add", "link.tex")
    git(seed, "commit", "-m", "link")
    git(seed, "push", "-q", "origin", "master")
    result = run(project, "pull", URL)
    assert "symlink" in result.output
    assert not (project / "paper").exists()


def test_pull_refuses_case_collision_with_workspace_file(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "Fig.png").write_text("workspace\n")
    commit_all(project)
    overleaf_edit(seed, "fig.png", "overleaf\n")
    result = run(project, "pull")
    assert "letter case" in result.output
    assert (project / "paper" / "Fig.png").read_text() == "workspace\n"


def test_publish_refuses_gitattributes_in_paper(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / ".gitattributes").write_text("* text=auto\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "change file contents" in result.output


def test_publish_pushes_committed_paper_and_root_bibliography(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "main.tex").write_text("reviewed\n")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    dry = run(project, "publish", "--dry-run")
    assert dry.exit_code == 0 and "nothing pushed" in dry.output
    assert git(seed, "ls-remote", "origin", "master") == before
    result = run(project, "publish", "--replace-bibliography")
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


@pytest.mark.parametrize("remote_text", ["remote edit\n", None])
def test_pull_keeps_committed_workspace_edits_on_conflict(setup, remote_text):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text("reviewed workspace edit\n")
    commit_all(project)
    before = (project / "paper/overleaf.json").read_bytes()
    overleaf_edit(seed, "main.tex", remote_text)
    result = run(project, "pull")
    assert result.exit_code != 0
    assert "Both workspace and Overleaf changed main.tex" in result.output
    assert (project / "paper/main.tex").read_text() == "reviewed workspace edit\n"
    assert (project / "paper/overleaf.json").read_bytes() == before
    assert not git(project, "status", "--porcelain")


def test_pull_preserves_local_edits_to_unchanged_remote_file(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed workspace edit\n")
    commit_all(project)
    overleaf_edit(seed, "old.tex", "remote edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper/main.tex").read_text() == "reviewed workspace edit\n"
    assert (project / "paper/old.tex").read_text() == "remote edit\n"


def test_pull_refuses_initial_import_over_existing_source(setup):
    _, project = setup
    (project / "paper").mkdir()
    (project / "paper/main.tex").write_text("existing paper\n")
    commit_all(project)
    result = run(project, "pull", URL)
    assert result.exit_code != 0
    assert (project / "paper/main.tex").read_text() == "existing paper\n"
    assert not (project / "paper/overleaf.json").exists()


def test_pull_refuses_directory_case_collision(setup):
    seed, project = setup
    for name in ["Figures/a.tex", "figures/b.tex"]:
        path = seed / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("figure\n")
        git(seed, "add", name)
    git(seed, "commit", "-m", "figures")
    git(seed, "push", "-q", "origin", "master")
    result = run(project, "pull", URL)
    assert result.exit_code != 0 and "letter case" in result.output
    assert not (project / "paper").exists()


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_refuses_executable_files(setup, command):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    repo = seed if command == "pull" else project
    name = "main.tex" if command == "pull" else "paper/main.tex"
    (repo / name).chmod(0o755)
    git(repo, "update-index", "--chmod=+x", name)
    git(repo, "commit", "-m", "executable")
    if command == "pull":
        git(seed, "push", "-q", "origin", "master")
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, command)
    assert result.exit_code != 0 and "executable" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize("target", ["real.bib", "missing.bib"])
def test_publish_refuses_symlinked_root_bibliography(setup, target):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "real.bib").write_text("@misc{root}\n")
    (project / "references.bib").unlink()
    os.symlink(target, project / "references.bib")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code != 0 and "regular non-executable" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize(
    "name",
    [
        "../escape.tex",
        ".git/config",
        "nested/.Git/config",
        "/absolute",
        "dir\\escape.tex",
    ],
)
def test_pull_refuses_unsafe_remote_tree_paths(setup, monkeypatch, name):
    _, project = setup
    real = module.tree
    monkeypatch.setattr(
        module,
        "tree",
        lambda repo, revision, prefix="": (
            {name: ("100644", "unused")}
            if repo.name == "overleaf"
            else real(repo, revision, prefix)
        ),
    )
    result = run(project, "pull", URL)
    assert result.exit_code != 0 and "unsafe path" in result.output
    assert not (project / "paper").exists()
    assert not (project / "escape.tex").exists()


def test_pull_refuses_ignored_symlink_destination(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / ".gitignore").write_text("/paper/figures\n")
    commit_all(project)
    outside = project.parent / "outside"
    outside.mkdir()
    os.symlink(outside, project / "paper/figures")
    (seed / "figures").mkdir()
    overleaf_edit(seed, "figures/a.tex", "remote figure\n")
    result = run(project, "pull")
    assert result.exit_code != 0 and "symlink" in result.output
    assert not (outside / "a.tex").exists()
    assert not git(project, "status", "--porcelain")


def test_pull_refuses_ignored_symlink_config(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    config = project / "paper/overleaf.json"
    outside = project.parent / "outside.json"
    outside.write_bytes(config.read_bytes())
    config.unlink()
    os.symlink(outside, config)
    git(project, "rm", "--cached", "--ignore-unmatch", "paper/overleaf.json")
    (project / ".gitignore").write_text("/paper/overleaf.json\n")
    commit_all(project)
    before = outside.read_bytes()
    result = run(project, "pull")
    assert result.exit_code != 0 and "symlink" in result.output
    assert outside.read_bytes() == before


def test_publish_requires_confirmation_after_pull_skips_remote_bibliography(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    overleaf_edit(seed, "references.bib", "@misc{collaborator}\n")
    assert run(project, "pull").exit_code == 0
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    metadata = (project / "paper/overleaf.json").read_bytes()
    dry = run(project, "publish", "--dry-run")
    assert dry.exit_code == 0 and "--replace-bibliography" in dry.output
    result = run(project, "publish")
    assert result.exit_code != 0 and "--replace-bibliography" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / "paper/overleaf.json").read_bytes() == metadata
    assert (seed / "references.bib").read_text() == "@misc{collaborator}\n"
    result = run(project, "publish", "--replace-bibliography")
    assert result.exit_code == 0, result.output


def test_publish_accepts_matching_bibliography_without_confirmation(setup):
    seed, project = setup
    (project / "references.bib").write_bytes((seed / "references.bib").read_bytes())
    commit_all(project)
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "reviewed edit\n"


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_refuses_duplicate_workspace_bibliography(setup, command):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    duplicate = project / "paper/references.bib"
    duplicate.write_text("@misc{paper_only}\n")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, command)
    assert result.exit_code != 0 and "canonical root bibliography" in result.output
    assert duplicate.read_text() == "@misc{paper_only}\n"
    assert git(seed, "ls-remote", "origin", "master") == before
    assert not git(project, "status", "--porcelain")


def test_publish_refuses_missing_root_bibliography(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "references.bib").unlink()
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish", "--replace-bibliography")
    assert result.exit_code != 0 and "canonical root references.bib" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize("setting", ["autocrlf", "filter", "hook"])
def test_publish_refuses_git_content_rewriting(setup, monkeypatch, setting):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    source = project / "paper/main.tex"
    source.write_bytes(b"reviewed\r\n")
    commit_all(project)
    config = project.parent / "global.gitconfig"
    if setting == "autocrlf":
        git(project, "config", "--file", str(config), "core.autocrlf", "true")
        git(project, "config", "core.autocrlf", "false")
    elif setting == "filter":
        attributes = project.parent / "attributes"
        attributes.write_text("*.tex filter=change\n")
        git(
            project,
            "config",
            "--file",
            str(config),
            "core.attributesFile",
            str(attributes),
        )
        git(
            project,
            "config",
            "--file",
            str(config),
            "filter.change.clean",
            "sed s/reviewed/rewritten/",
        )
        git(project, "config", "core.attributesFile", os.devnull)
    else:
        hooks = project.parent / "hooks"
        hooks.mkdir()
        hook = hooks / "pre-commit"
        hook.write_text(
            "#!/bin/sh\nprintf 'rewritten\\n' > main.tex\ngit add main.tex\n"
        )
        hook.chmod(0o755)
        git(project, "config", "--file", str(config), "core.hooksPath", str(hooks))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    before = git(seed, "ls-remote", "origin", "master")
    metadata = (project / "paper/overleaf.json").read_bytes()
    result = run(project, "publish", "--replace-bibliography")
    assert result.exit_code != 0 and "nothing pushed" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / "paper/overleaf.json").read_bytes() == metadata
    assert source.read_bytes() == b"reviewed\r\n"
