"""Tests for `asta workspace overleaf pull|publish` against a local bare remote."""

import importlib
import json
import os
import subprocess
from pathlib import Path

import click
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


@pytest.mark.parametrize("state", ["absent", "ignored", "untracked"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_without_committed_root_bib_never_deletes_remote_bib(
    setup, state, dry_run
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    git(project, "rm", "references.bib")
    if state == "ignored":
        (project / ".gitignore").write_text("/references.bib\n")
    commit_all(project)
    if state != "absent":
        (project / "references.bib").write_text("@misc{uncommitted}\n")
    before = git(seed, "ls-remote", "origin", "master")
    metadata = (project / "paper" / "overleaf.json").read_bytes()
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert result.exit_code == 1, result.output
    assert (
        "Commit a root references.bib" in result.output
        or "local changes" in result.output
    )
    assert not isinstance(result.exception, KeyError)
    assert git(seed, "ls-remote", "origin", "master") == before
    assert git(seed, "show", "HEAD:references.bib") == "@misc{overleaf}"
    assert (project / "paper" / "overleaf.json").read_bytes() == metadata


def test_pull_refuses_changed_project_url_before_cloning(setup, monkeypatch):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)

    def unexpected_clone(*args):
        pytest.fail("A changed project URL must be refused before cloning")

    monkeypatch.setattr(module, "clone", unexpected_clone)
    result = run(project, "pull", "https://git.overleaf.com/7654321")
    assert result.exit_code == 1 and "different Overleaf project" in result.output
    assert not git(project, "status", "--porcelain")


def test_pull_reports_missing_base_without_changing_paper(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    config = project / "paper" / "overleaf.json"
    config.write_text(json.dumps({"url": URL, "base": "0" * 40}))
    commit_all(project)
    result = run(project, "pull")
    assert result.exit_code == 1 and "base is missing from its history" in result.output
    assert "separate --dir" in result.output
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize(
    "contents",
    [
        "{",
        "[]",
        "null",
        "1",
        '{"base": "bad"}',
        json.dumps({"base": "0" * 40, "url": 42}),
        json.dumps({"base": int("1" * 40), "url": URL}),
    ],
)
@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_reports_invalid_metadata_without_traceback(setup, contents, command):
    _, project = setup
    paper = project / "paper"
    paper.mkdir()
    (paper / "overleaf.json").write_text(contents)
    commit_all(project)
    result = run(project, command)
    assert result.exit_code == 1 and "Error:" in result.output
    assert isinstance(result.exception, SystemExit)
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("contents", ["@misc{root}\n", "@misc{paper}\n"])
def test_publish_checks_paper_bibliography_collision(setup, contents):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "references.bib").write_text(contents)
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    if contents == "@misc{root}\n":
        assert result.exit_code == 0, result.output
        git(seed, "pull", "origin", "master")
        assert (seed / "references.bib").read_text() == contents
    else:
        assert (
            result.exit_code == 1 and "differs from the canonical root" in result.output
        )
        assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_ignores_inherited_repository_routing(setup, monkeypatch, command):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    with monkeypatch.context() as patch:
        for name in module.GIT_LOCAL_ENV:
            patch.setenv(name, "invalid-hook-routing")
        result = run(project, command)
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "name",
    ["../escape.tex", "sub/../../escape.tex", "sub/.GiT/config", "sub\\..\\escape.tex"],
)
def test_tree_refuses_unsafe_paths(monkeypatch, tmp_path, name):
    monkeypatch.setattr(
        module,
        "git_bytes",
        lambda *a, **k: f"100644 blob {'0' * 40}\t{name}\0".encode(),
    )
    with pytest.raises(module.click.ClickException, match="unsafe Git path"):
        module.files(tmp_path, "HEAD")


@pytest.mark.parametrize(
    "args,message",
    [
        (("cat-file", "blob", "401"), "git cat-file failed"),
        (("clone", URL), "Overleaf authentication failed"),
        (("-c", "credential.helper=", "clone", URL), "Overleaf authentication failed"),
        (("push", "origin", "HEAD"), "Overleaf authentication failed"),
    ],
)
def test_git_maps_authentication_errors_only_for_transport(
    monkeypatch, tmp_path, args, message
):
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 1, b"", b"401 authentication failed"
        ),
    )
    with pytest.raises(module.click.ClickException, match=message):
        module.git_bytes(*args, cwd=tmp_path)


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


@pytest.mark.parametrize("direction", ["file-to-directory", "directory-to-file"])
def test_pull_refuses_path_structure_collisions_before_any_writes(setup, direction):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    paper = project / "paper"
    if direction == "file-to-directory":
        (paper / "extra").write_text("workspace-only file\n")
        (seed / "extra").mkdir()
        (seed / "extra" / "part.tex").write_text("remote\n")
    else:
        (paper / "extra").mkdir()
        (paper / "extra" / "part.tex").write_text("workspace-only file\n")
        (seed / "extra").write_text("remote\n")
    commit_all(project)
    metadata = (paper / "overleaf.json").read_bytes()
    overleaf_edit(seed, "main.tex", "an earlier non-conflicting change\n")
    git(seed, "add", "extra")
    git(seed, "commit", "-m", "colliding path")
    git(seed, "push", "origin", "master")
    result = run(project, "pull")
    assert result.exit_code == 1 and "path collision" in result.output, result.output
    assert (paper / "main.tex").read_text() == "hello\n"
    assert (paper / "overleaf.json").read_bytes() == metadata
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize(
    "names", [("Foo.tex", "foo.tex"), ("Foo/a.tex", "foo/b.tex"), ("Overleaf.json",)]
)
def test_pull_refuses_case_collisions_even_on_case_sensitive_filesystems(setup, names):
    seed, project = setup
    for name in names:
        target = seed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("remote\n")
    git(seed, "add", *names)
    git(seed, "commit", "-m", "case collision")
    git(seed, "push", "origin", "master")
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "case-insensitive" in result.output, result.output
    assert not (project / "paper").exists()


def test_pull_refuses_case_collision_with_workspace_only_file(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "Extra.tex").write_text("workspace only\n")
    commit_all(project)
    overleaf_edit(seed, "extra.tex", "remote\n")
    result = run(project, "pull")
    assert result.exit_code == 1 and "case-insensitive" in result.output, result.output
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("failure", ["blob", "metadata"])
def test_pull_keeps_original_paper_on_staging_failure(setup, monkeypatch, failure):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    metadata = (paper / "overleaf.json").read_bytes()
    overleaf_edit(seed, "main.tex", "remote\n")
    overleaf_edit(seed, "old.tex", None)
    real = module.write_blob if failure == "blob" else module.save_config

    def fail_after_write(*args):
        real(*args)
        raise OSError("fixture write failure")

    monkeypatch.setattr(
        module, "write_blob" if failure == "blob" else "save_config", fail_after_write
    )
    result = run(project, "pull")
    assert result.exit_code == 1 and "Could not update paper" in result.output
    assert (paper / "main.tex").read_text() == "hello\n"
    assert (paper / "old.tex").read_text() == "old\n"
    assert (paper / "overleaf.json").read_bytes() == metadata
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("restore_fails", [False, True])
def test_pull_preserves_original_when_directory_replacement_fails(
    setup, monkeypatch, restore_fails
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    metadata = (paper / "overleaf.json").read_bytes()
    overleaf_edit(seed, "main.tex", "remote\n")
    rename = Path.rename

    def fail_replacement(path, target):
        if path.name == "staged" or (restore_fails and path.name == "original"):
            raise OSError("fixture rename failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_replacement)
    result = run(project, "pull")
    assert result.exit_code == 1
    if restore_fails:
        backups = list(project.glob("tmp*/original"))
        assert len(backups) == 1
        original = backups[0]
        assert "original is preserved at" in result.output
        assert str(original) in result.output
    else:
        original = paper
        assert "Could not update paper" in result.output
        assert not git(project, "status", "--porcelain")
    assert (original / "main.tex").read_text() == "hello\n"
    assert (original / "overleaf.json").read_bytes() == metadata


def test_pull_preserves_ignored_outputs_and_workspace_file_modes(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    paper = project / "paper"
    (paper / ".gitignore").write_text("*.pdf\n")
    (paper / "latexmkrc").write_text("# workspace only\n")
    (paper / "latexmkrc").chmod(0o755)
    commit_all(project)
    (paper / "preview.pdf").write_bytes(b"existing generated output")
    overleaf_edit(seed, "main.tex", "remote\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (paper / "main.tex").read_text() == "remote\n"
    assert (paper / "preview.pdf").read_bytes() == b"existing generated output"
    assert (paper / "latexmkrc").read_text() == "# workspace only\n"
    assert git(project, "diff", "--name-only").splitlines() == [
        "paper/main.tex",
        "paper/overleaf.json",
    ]


@pytest.mark.parametrize(
    "url", ["https://example.com/x", "https://git:pw@git.overleaf.com/1", "", None]
)
def test_rejects_non_overleaf_urls(setup, url):
    _, project = setup
    result = run(project, "pull", *([url] if url is not None else []))
    assert result.exit_code != 0
    assert "git.overleaf.com/<project-id>" in result.output


@pytest.mark.skipif(os.name == "nt", reason="POSIX credential helper")
def test_token_uses_ephemeral_helper_and_disables_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("TMPDIR", str(tmp_path / "nonexistent-noexec-temp"))
    with module.credentials() as (env, options):
        assert options[:2] == ["-c", "credential.helper="]
        assert "fixture-token" not in " ".join(options)
        answer = subprocess.run(
            ["git", *options, "credential", "fill"],
            env=env,
            capture_output=True,
            input="protocol=https\nhost=git.overleaf.com\n\n",
            text=True,
        )
        assert answer.returncode == 0
        assert "username=git\npassword=fixture-token" in answer.stdout
        stored = subprocess.run(
            ["git", *options, "credential", "approve"],
            env=env,
            capture_output=True,
            input=answer.stdout,
            text=True,
        )
        assert stored.returncode == 0 and not stored.stdout
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("autocrlf", [False, True])
def test_pull_compares_normalized_line_endings(setup, autocrlf):
    seed, project = setup
    (seed / "main.tex").write_bytes(b"hello\r\n")
    git(seed, "add", "main.tex")
    git(seed, "commit", "-m", "CRLF")
    git(seed, "push", "origin", "master")
    if autocrlf:
        git(project, "config", "core.autocrlf", "true")
    else:
        (project / ".gitattributes").write_text("paper/*.tex text eol=lf\n")
        commit_all(project)
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (seed / "main.tex").write_bytes(b"collaborator edit\r\n")
    git(seed, "add", "main.tex")
    git(seed, "commit", "-m", "CRLF edit")
    git(seed, "push", "origin", "master")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper" / "main.tex").read_text() == "collaborator edit\n"
    commit_all(project)
    assert run(project, "publish").exit_code == 0


@pytest.mark.parametrize("side", ["workspace", "overleaf"])
@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_refuses_git_filters_before_changing_files(setup, side, command):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    repo = project if side == "workspace" else seed
    pattern = "paper/*.tex" if side == "workspace" else "*.tex"
    (repo / ".gitattributes").write_text(f"{pattern} filter=lfs\n")
    commit_all(repo)
    if side == "overleaf":
        git(seed, "push", "origin", "master")
        if command == "publish":
            config = project / "paper" / "overleaf.json"
            config.write_text(
                json.dumps({"url": URL, "base": git(seed, "rev-parse", "HEAD")})
            )
            commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    metadata = (project / "paper" / "overleaf.json").read_bytes()
    result = run(project, command)
    assert result.exit_code == 1 and "custom Git filters" in result.output, (
        result.output
    )
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / "paper" / "overleaf.json").read_bytes() == metadata
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("configured", [True, False])
def test_publish_transfers_repo_local_identity_or_uses_fallback(
    setup, monkeypatch, configured
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "main.tex").write_text("publish me\n")
    commit_all(project)
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(key)
    if configured:
        git(project, "config", "user.name", "Local Author")
        git(project, "config", "user.email", "local@example.invalid")
    else:
        monkeypatch.setenv("EMAIL", "")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "origin", "master")
    expected = (
        "Local Author <local@example.invalid>"
        if configured
        else "Asta Workspace <asta-workspace@example.invalid>"
    )
    assert git(seed, "log", "-1", "--format=%cn <%ce>") == expected


@pytest.mark.parametrize(
    "directory",
    [
        ".git",
        ".git/hooks",
        "paper/../.git/hooks",
        ".git./hooks",
        "GIT~1/hooks",
        "paper:stream",
    ],
)
def test_pull_refuses_administrative_and_windows_alias_directories(setup, directory):
    _, project = setup
    result = run(project, "pull", URL, "--dir", directory)
    assert result.exit_code == 1 and "unsafe Git path" in result.output, result.output
    assert not (project / ".git" / "hooks" / "main.tex").exists()


def test_validate_paths_refuses_unicode_aliases():
    with pytest.raises(click.ClickException, match="case-insensitive path collision"):
        module.validate_paths(["caf\u00e9/main.tex", "cafe\u0301/other.tex"])


@pytest.mark.parametrize(
    "error, message",
    [
        (b"Could not resolve host: private-host", "Check DNS"),
        (b"SSL certificate problem: private-ca", "trust store"),
        (
            b"repository 'https://git:fixture-secret@git.overleaf.com/x' not found",
            "project not found",
        ),
        (b"Failed to connect to private-host", "Check your network"),
    ],
)
def test_network_errors_are_actionable_without_echoing_stderr(
    tmp_path, monkeypatch, error, message
):
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 128, b"", error),
    )
    with pytest.raises(click.ClickException, match=message) as caught:
        module.git("clone", URL, cwd=tmp_path)
    assert "private-" not in str(caught.value)
    assert "fixture-secret" not in str(caught.value)


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_publish_preserves_executable_mode_with_filemode_disabled(setup, monkeypatch):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "main.tex").chmod(0o755)
    commit_all(project)
    real = module.clone

    def clone_with_filemode_disabled(url, repo):
        head = real(url, repo)
        git(repo, "config", "core.fileMode", "false")
        return head

    monkeypatch.setattr(module, "clone", clone_with_filemode_disabled)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "origin", "master")
    assert git(seed, "ls-tree", "HEAD", "main.tex").startswith("100755")


def test_sync_between_sha256_workspace_and_sha1_overleaf(setup):
    seed, original = setup
    project = original.parent / "sha256-project"
    project.mkdir()
    git(project, "init", "-b", "main", "--object-format=sha256")
    (project / "references.bib").write_text("@misc{overleaf}\n")
    commit_all(project)
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    assert "differs from the workspace root copy" not in result.output
    commit_all(project)
    overleaf_edit(seed, "main.tex", "remote edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    (project / "paper" / "main.tex").write_text("workspace edit\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "origin", "master")
    assert (seed / "main.tex").read_text() == "workspace edit\n"
    config = json.loads((project / "paper" / "overleaf.json").read_text())
    assert config["base"] == git(seed, "rev-parse", "HEAD")
    assert len(config["base"]) == 40
    assert len(git(project, "rev-parse", "HEAD")) == 64


def test_pull_refuses_separate_git_administrative_directory(setup):
    _, project = setup
    git(project, "init", "--separate-git-dir", str(project / "admin"))
    result = run(project, "pull", URL, "--dir", "admin/hooks")
    assert result.exit_code == 1 and "administrative directory" in result.output
    assert not (project / "admin" / "hooks" / "main.tex").exists()


def test_pull_refuses_remote_filters_before_running_their_drivers(
    setup, monkeypatch, tmp_path
):
    seed, project = setup
    marker = tmp_path / "smudged"
    config = tmp_path / "gitconfig"
    config.write_text(f'[filter "probe"]\n\tsmudge = "touch {marker}; cat"\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    (seed / ".gitattributes").write_text("*.tex filter=probe\n")
    commit_all(seed)
    git(seed, "push", "-q", "origin", "master")
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "custom Git filters" in result.output, (
        result.output
    )
    assert not marker.exists()
    assert not (project / "paper").exists()


def test_publish_refuses_uncommitted_workspace_attributes(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / ".gitattributes").write_text("*.tex eol=crlf\n")
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code == 1 and ".gitattributes" in result.output, result.output
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_refuses_symlinked_metadata_before_reading_it(setup, tmp_path, command):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    outside = tmp_path / "outside.json"
    outside.write_bytes((project / "paper" / "overleaf.json").read_bytes())
    (project / "paper" / "overleaf.json").unlink()
    (project / "paper" / "overleaf.json").symlink_to(outside)
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    original = outside.read_bytes()
    result = run(project, command)
    assert result.exit_code == 1 and "must not be a symlink" in result.output, (
        result.output
    )
    assert outside.read_bytes() == original
    assert git(seed, "ls-remote", "origin", "master") == before
