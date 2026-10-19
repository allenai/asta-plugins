"""Tests for `asta workspace overleaf pull|publish` against a local bare remote."""

import importlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from asta.cli import cli

module = importlib.import_module("asta.commands.overleaf")
CONFLICT_EXIT = module.CONFLICT_EXIT
URL = "https://git.overleaf.com/1234567"


def _record(paper):
    """The pairing record for a paper directory directly under the workspace."""
    path = paper.parent / ".asta/overleaf" / f"{paper.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run(project, *args, merge=True):
    if merge and args[:1] == ("publish",):
        # Stand in for merging the reviewed revision into origin's default branch.
        subprocess.run(
            ["git", "push", "-q", "-f", "--no-verify", "origin", "HEAD:main"],
            cwd=project,
            check=True,
            capture_output=True,
        )
    return CliRunner().invoke(
        cli, ["workspace", "overleaf", *args, "--project", str(project)]
    )


@pytest.mark.parametrize(
    "scope", ["https://git.overleaf.com", URL, "https://git@git.overleaf.com"]
)
@pytest.mark.skipif(os.name == "nt", reason="POSIX askpass")
def test_token_bypasses_url_scoped_store_helper(setup, monkeypatch, scope):
    _, project = setup
    config = project.parent / "credentials-config"
    stored = project.parent / "stored-credentials"
    stored.write_text("https://git:stale-fixture@git.overleaf.com/1234567\n")
    before = stored.read_bytes()
    git(project, "config", "--file", str(config), "credential.useHttpPath", "true")
    git(
        project,
        "config",
        "--file",
        str(config),
        f"credential.{scope}.helper",
        f"store --file={stored}",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    request = b"protocol=https\nhost=git.overleaf.com\npath=1234567\nusername=git\n"
    with module.credentials() as (env, options):
        filled = subprocess.run(
            ["git", *options, "credential", "fill"],
            cwd=project,
            env=env,
            input=request + b"\n",
            check=True,
            capture_output=True,
        ).stdout
        assert b"password=fixture-token\n" in filled
        assert b"stale-fixture" not in filled
        subprocess.run(
            ["git", *options, "credential", "approve"],
            cwd=project,
            env=env,
            input=filled + b"\n",
            check=True,
            capture_output=True,
        )
    assert stored.read_bytes() == before


def test_personal_credential_helper_remains_available(setup, monkeypatch):
    _, project = setup
    config = project.parent / "credentials-config"
    stored = project.parent / "stored-credentials"
    stored.write_text("https://git:personal-fixture@git.overleaf.com\n")
    git(
        project,
        "config",
        "--file",
        str(config),
        "credential.https://git.overleaf.com.helper",
        f"store --file={stored}",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    with module.credentials() as (env, options):
        filled = subprocess.run(
            ["git", *options, "credential", "fill"],
            cwd=project,
            env=env,
            input=b"protocol=https\nhost=git.overleaf.com\nusername=git\n\n",
            check=True,
            capture_output=True,
        ).stdout
    assert b"password=personal-fixture\n" in filled


def test_git_failure_with_only_options_has_sanitized_error(tmp_path):
    with pytest.raises(module.GitCommandError, match="git command failed") as error:
        module.git_bytes("--invalid-fixture-option", cwd=tmp_path)
    assert module.RECOVERY not in error.value.format_message()


@pytest.mark.parametrize(
    "operation,diagnostic,guidance",
    [
        (
            "commit",
            b"fixture-secret signer failed",
            "commit hooks and signing settings",
        ),
        (
            "push",
            b"pre-push hook declined: fixture-secret",
            "Workspace pre-push hook failed",
        ),
        ("push", b"fixture-secret", "Also check workspace pre-push hooks"),
    ],
)
def test_git_failure_gives_local_guidance_without_echoing_diagnostics(
    tmp_path, monkeypatch, operation, diagnostic, guidance
):
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(a[0], 1, b"", diagnostic)
        ),
    )
    with pytest.raises(module.click.ClickException, match=guidance) as error:
        module.git_bytes(operation, cwd=tmp_path)
    assert "fixture-secret" not in str(error.value)


def test_sync_preserves_whitespace_in_repository_root(setup):
    _, project = setup
    renamed = project.with_name(" project ")
    project.rename(renamed)
    result = run(renamed, "pull", URL)
    assert result.exit_code == 0, result.output
    commit_all(renamed)
    assert run(renamed, "publish", "--dry-run").exit_code == 0


def test_git_environment_removes_all_repository_overrides(tmp_path, monkeypatch):
    local_names = git(tmp_path, "rev-parse", "--local-env-vars").splitlines()
    # Older Git versions report this internal override; newer versions omit it.
    overrides = [*local_names, "GIT_NAMESPACE", "GIT_INTERNAL_SUPER_PREFIX"]
    for name in overrides:
        monkeypatch.setenv(name, "fixture-override")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "personal-config")
    env = module.git_environment()
    assert not set(overrides) & env.keys()
    assert env["GIT_CONFIG_GLOBAL"] == "personal-config"


@pytest.mark.parametrize("operation", ["clone", "push"])
@pytest.mark.parametrize("code", ["401", "403"])
def test_transport_project_ids_do_not_report_auth_errors(
    tmp_path, monkeypatch, operation, code
):
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(
                a[0],
                128,
                b"",
                f"fatal: unable to access https://git.overleaf.com/{code}: Could not resolve host".encode(),
            )
        ),
    )
    with pytest.raises(module.click.ClickException, match=f"git {operation} failed"):
        module.git_bytes(operation, cwd=tmp_path)


@pytest.mark.parametrize(
    "diagnostic,reason",
    [
        (b"HTTP/2 401", "authentication failed"),
        (b"The requested URL returned error: 403", "access denied"),
        (b"fatal: Authentication failed", "authentication failed"),
        (
            b"fatal: could not read Username: terminal prompts disabled",
            "authentication failed",
        ),
        (
            b"fatal: could not read Password: terminal prompts disabled",
            "authentication failed",
        ),
        (b"Authentifizierung fehlgeschlagen (HTTP/2 401)", "authentication failed"),
        (b"Zugriff verweigert (HTTP/2 403)", "access denied"),
        (b"Authentifizierung fehlgeschlagen", "Check your Overleaf credentials"),
    ],
)
def test_transport_auth_errors_are_actionable(
    tmp_path, monkeypatch, diagnostic, reason
):
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    assert module.git_environment()["LC_ALL"] == "de_DE.UTF-8"
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(a[0], 128, b"", diagnostic)
        ),
    )
    with pytest.raises(module.click.ClickException, match=reason):
        module.git_bytes("clone", cwd=tmp_path)


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_reports_unborn_workspace_head(tmp_path, command):
    git(tmp_path, "init", "-b", "main")
    result = run(tmp_path, command, *([URL] if command == "pull" else []), merge=False)
    assert result.exit_code != 0
    assert "Commit the workspace's initial files" in result.output


@pytest.fixture
def setup(tmp_path, monkeypatch, request):
    workspace_format = getattr(request, "param", "sha1")
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
        lambda *a, **k: real(
            *(
                str(remote)
                if x in (URL, URL.replace("https://", "https://git@", 1))
                else x
                for x in a
            ),
            **k,
        ),
    )
    git(tmp_path, "init", "--bare", "-b", "master", str(remote))
    # A push otherwise starts background auto-maintenance in the remote, whose
    # repack can delete pack files while a local clone of it is copying them.
    git(remote, "config", "receive.autogc", "false")
    git(remote, "config", "maintenance.auto", "false")
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
    git(project, "init", f"--object-format={workspace_format}", "-b", "main")
    (project / "references.bib").write_text("@misc{root}\n")
    git(project, "add", ".")
    git(project, "commit", "-m", "init")
    origin = tmp_path / "workspace.git"
    git(
        tmp_path,
        "init",
        f"--object-format={workspace_format}",
        "--bare",
        "-q",
        "-b",
        "main",
        str(origin),
    )
    git(project, "remote", "add", "origin", str(origin))
    git(project, "push", "-q", "origin", "main")
    return seed, project


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


def prepare_expected_publication(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("checked paper\n")
    commit_all(project)
    git(project, "push", "origin", "main")
    return seed, project, git(project, "rev-parse", "HEAD")


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_expected_publish_accepts_the_checked_tip(setup, dry_run):
    seed, project, expected = prepare_expected_publication(setup)
    result = run(
        project,
        "publish",
        "--expected-commit",
        expected,
        *(["--dry-run"] if dry_run else []),
        merge=False,
    )
    assert result.exit_code == 0, result.output
    if not dry_run:
        git(seed, "pull", "--ff-only")
        assert (
            git(seed, "log", "-1", "--format=%s")
            == f"Publish workspace commit {expected}"
        )


@pytest.mark.parametrize("expected", ["short", "a" * 39, "a" * 41, "a" * 63, "a" * 65])
def test_expected_publish_rejects_partial_commit_ids(setup, expected):
    _, project = setup
    result = run(project, "publish", "--expected-commit", expected, merge=False)
    assert result.exit_code == 2 and "full commit id" in result.output


def test_expected_publish_requires_the_exact_checkout(setup):
    seed, project, _ = prepare_expected_publication(setup)
    expected = git(project, "rev-parse", "HEAD~1")
    before = git(seed, "ls-remote", "origin", "HEAD")
    result = run(project, "publish", "--expected-commit", expected, merge=False)
    assert result.exit_code == 1 and "Check out the expected" in result.output
    assert git(seed, "ls-remote", "origin", "HEAD") == before


def test_expected_publish_refuses_a_new_tip_even_with_identical_paper(setup):
    seed, project, expected = prepare_expected_publication(setup)
    git(project, "commit", "--allow-empty", "-m", "New merge, same paper")
    git(project, "push", "origin", "main")
    git(project, "checkout", expected)
    before = git(seed, "ls-remote", "origin", "HEAD")
    result = run(project, "publish", "--expected-commit", expected, merge=False)
    assert result.exit_code == 1 and "default branch changed" in result.output
    assert git(seed, "ls-remote", "origin", "HEAD") == before


@pytest.mark.parametrize(
    "change", ["paper", "unrelated", "default_branch", "unavailable"]
)
def test_expected_publish_rechecks_origin_after_preparing_the_export(
    setup, monkeypatch, change
):
    seed, project, expected = prepare_expected_publication(setup)
    before = git(seed, "ls-remote", "origin", "HEAD")
    origin = project.parent / "workspace.git"
    merger = project.parent / "merger"
    git(project.parent, "clone", str(origin), str(merger))
    real = module.git
    changed = False

    def advance(*args, **kwargs):
        nonlocal changed
        result = real(*args, **kwargs)
        if "commit" in args and kwargs["cwd"].name == "overleaf":
            changed = True
            if change == "unavailable":
                git(project, "remote", "remove", "origin")
            elif change == "default_branch":
                git(merger, "push", "origin", "HEAD:release")
                git(origin, "symbolic-ref", "HEAD", "refs/heads/release")
            else:
                path = merger / ("paper/main.tex" if change == "paper" else "README.md")
                path.write_text("New reviewed change\n")
                commit_all(merger)
                git(merger, "push", "origin", "main")
        return result

    monkeypatch.setattr(module, "git", advance)
    result = run(project, "publish", "--expected-commit", expected, merge=False)
    assert changed and result.exit_code == 1, result.output
    assert "nothing pushed" in result.output
    assert (
        "Could not verify origin"
        if change == "unavailable"
        else "default branch changed"
    ) in result.output
    assert git(seed, "ls-remote", "origin", "HEAD") == before


def test_pull_preserves_paper_bibliography_and_workspace_root(setup):
    seed, project = setup
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    paper = project / "paper"
    assert (paper / "main.tex").read_text() == "hello\n"
    assert (paper / "references.bib").read_bytes() == (
        seed / "references.bib"
    ).read_bytes()
    assert (project / "references.bib").read_text() == "@misc{root}\n"
    config = json.loads(_record(paper).read_text())
    assert config == {
        "format": module.FORMAT,
        "requires_asta": module.FORMAT_RELEASE,
        "url": URL,
        "base": git(seed, "rev-parse", "HEAD"),
    }


def test_pull_parent_file_collision_leaves_all_sources_unchanged(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / ".gitignore").write_text("paper/figs\n!paper/figs/\n")
    commit_all(project)
    (project / "paper/figs").write_text("local ignored notes\n")
    overleaf_edit(seed, "old.tex", None)
    (seed / "figs").mkdir()
    overleaf_edit(seed, "figs/a.tex", "remote figure\n")
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    result = run(project, "pull")
    assert result.exit_code != 0 and "is a file needed as a directory" in result.output
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before


def test_pull_reports_file_blocking_selected_directory(setup):
    _, project = setup
    (project / "papers").write_text("local notes\n")
    result = run(project, "pull", URL, "--dir", "papers/article")
    assert result.exit_code != 0 and "is a file needed as a directory" in result.output
    assert (project / "papers").read_text() == "local notes\n"


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


@pytest.mark.parametrize("initial_import", [True, False])
@pytest.mark.parametrize("during_clone", [True, False])
def test_pull_preserves_untracked_sources(
    setup, monkeypatch, initial_import, during_clone
):
    seed, project = setup
    paper = project / "paper"
    if initial_import:
        paper.mkdir()
        name = "main.tex"
    else:
        assert run(project, "pull", URL).exit_code == 0
        commit_all(project)
        name = "new.tex"
        overleaf_edit(seed, "old.tex", None)
        overleaf_edit(seed, name, "remote source\n")
    before = {p.name: p.read_bytes() for p in paper.iterdir()}
    target = paper / name
    if during_clone:
        real = module.clone

        def clone(*args):
            head = real(*args)
            target.write_text("uncommitted local source\n")
            return head

        monkeypatch.setattr(module, "clone", clone)
    else:
        target.write_text("uncommitted local source\n")
        git(project, "config", "status.showUntrackedFiles", "no")
        assert git(project, "status", "--porcelain") == ""
    result = run(project, "pull", *([URL] if initial_import else []))
    assert result.exit_code != 0 and "local changes" in result.output
    assert target.read_text() == "uncommitted local source\n"
    assert {p.name: p.read_bytes() for p in paper.iterdir()} == {
        **before,
        name: b"uncommitted local source\n",
    }


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
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


@pytest.mark.parametrize(
    ("old", "new"), [("old.tex", "Old.tex"), ("café.tex", "cafe\u0301.tex")]
)
@pytest.mark.parametrize("aliasing_filesystem", [False, True])
def test_pull_rename_preserves_files_or_refuses_existing_alias(
    setup, monkeypatch, old, new, aliasing_filesystem
):
    seed, project = setup
    if old != "old.tex":
        git(seed, "mv", "old.tex", old)
        git(seed, "commit", "-m", "name")
        git(seed, "push", "-q", "origin", "master")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    before = {p.name: p.read_bytes() for p in paper.iterdir()}
    git(seed, "mv", old, new)
    (seed / new).write_text("renamed remote source\n")
    (seed / "main.tex").write_text("collaborator edit\n")
    git(seed, "add", "--", new, "main.tex")
    git(seed, "commit", "-m", "rename and edit")
    git(seed, "push", "-q", "origin", "master")
    exists = module.Path.exists
    destination_exists = exists(paper / new)
    if aliasing_filesystem:
        # Model an existing destination alias, as on a case/NFC-insensitive volume.
        monkeypatch.setattr(
            module.Path,
            "exists",
            lambda path: exists(paper / old) if path == paper / new else exists(path),
        )
    result = run(project, "pull")
    if aliasing_filesystem or destination_exists:
        assert result.exit_code != 0, result.output
        assert {p.name: p.read_bytes() for p in paper.iterdir()} == before
    else:
        assert result.exit_code == 0, result.output
        assert not (paper / old).exists()
        assert (paper / new).read_bytes() == (seed / new).read_bytes()
        assert (paper / "main.tex").read_bytes() == (seed / "main.tex").read_bytes()
        assert json.loads(_record(paper).read_text())["base"] == git(
            seed, "rev-parse", "HEAD"
        )


def test_publish_refuses_gitattributes_in_paper(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / ".gitattributes").write_text("* text=auto\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "change file contents" in result.output


def test_publish_pushes_committed_paper_without_injecting_workspace_bibliography(setup):
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
    assert (seed / "references.bib").read_text() == "@misc{overleaf}\n"
    assert not (seed / "overleaf.json").exists()
    assert not git(project, "status", "--porcelain")
    again = run(project, "publish")
    assert again.exit_code == 0 and "already matches" in again.output


def test_commands_find_the_paired_paper_without_dir(setup):
    seed, project = setup
    paper = project / "examples/workspace/paper"
    result = run(project, "pull", URL, "--dir", "examples/workspace/paper")
    assert result.exit_code == 0, result.output
    commit_all(project)
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (paper / "main.tex").read_text() == "collaborator edit\n"
    assert not (project / "paper").exists()
    (paper / "main.tex").write_text("reviewed\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "reviewed\n"


def test_pairing_records_live_outside_each_paper_directory(setup):
    _, project = setup
    for directory in ("paper", "examples/workspace/paper"):
        assert run(project, "pull", URL, "--dir", directory).exit_code == 0
        assert not (project / directory / "overleaf.json").exists()
    records = project / ".asta/overleaf"
    assert json.loads((records / "paper.json").read_text())["url"] == URL
    nested = records / "examples/workspace/paper.json"
    assert json.loads(nested.read_text())["url"] == URL


def test_sync_without_dir_handles_every_paired_paper(setup, monkeypatch):
    _, project = setup
    for directory in ("paper", "examples/workspace/paper"):
        assert run(project, "pull", URL, "--dir", directory).exit_code == 0
    commit_all(project)
    synced = []
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    monkeypatch.setattr(
        sync_module, "sync_workspace", lambda _, directory: synced.append(directory)
    )
    result = run(project, "sync")
    assert result.exit_code == 0, result.output
    assert synced == ["examples/workspace/paper", "paper"]
    synced.clear()
    result = run(project, "sync", "--dir", "paper")
    assert result.exit_code == 0, result.output
    assert synced == ["paper"]


@pytest.mark.parametrize("failure", ["sync", "check"])
@pytest.mark.parametrize("error_kind", ["sync", "git", "format"])
def test_sync_attempts_remaining_papers_after_each_failure(
    setup, monkeypatch, failure, error_kind
):
    _, project = setup
    for directory in ("a", "b", "c"):
        assert run(project, "pull", URL, "--dir", directory).exit_code == 0
    commit_all(project)
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    gate_module = importlib.import_module("asta.commands.overleaf_gate")
    attempted = []
    synced = []

    def fail_some(_, directory, *args):
        attempted.append(directory)
        if directory in {"a", "c"}:
            message = f"fixture failure in {directory}"
            if error_kind == "git":
                raise module.GitCommandError(message, 128)
            if error_kind == "format":
                raise module.NewerFormatError(message)
            raise module.SyncError(message)
        if failure == "sync":
            synced.append(directory)

    monkeypatch.setattr(
        sync_module,
        "sync_workspace",
        fail_some
        if failure == "sync"
        else lambda _, directory: synced.append(directory),
    )
    monkeypatch.setattr(gate_module, "require_release_check", fail_some)
    options = ["--check-repo", "owner/check"] if failure == "check" else []
    result = run(project, "sync", *options)
    assert result.exit_code == 1, result.output
    assert attempted == ["a", "b", "c"]
    assert synced == ["b"]
    for directory in ("a", "c"):
        assert f"{directory}: fixture failure in {directory}" in result.output
    assert "Sync failed for: a, c. All paired papers were attempted." in result.output


@pytest.mark.parametrize(
    "name", [".json", "-paper.json", "nested/-paper.json", "bad\nname.json"]
)
def test_discovery_refuses_invalid_pairing_record_names(setup, name):
    _, project = setup
    record = project / ".asta/overleaf" / name
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"url": URL, "base": "a" * 40}))
    commit_all(project)
    result = run(project, "sync")
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)
    assert "unsafe path" in result.output or "Invalid paper directory" in result.output


@pytest.mark.parametrize("directory", ["-paper", "nested/-paper"])
def test_pull_refuses_undiscoverable_paper_names_before_copying(
    setup, monkeypatch, directory
):
    _, project = setup

    def refuse_clone(*args):
        pytest.fail("invalid paper names must be rejected before cloning Overleaf")

    monkeypatch.setattr(module, "clone", refuse_clone)
    result = run(project, "pull", URL, f"--dir={directory}")
    assert result.exit_code == 1, result.output
    assert "Directory components must not start with '-'" in result.output
    assert not (project / directory).exists()
    assert not (project / ".asta/overleaf").exists()


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_commands_refuse_ambiguous_pairings_without_dir(setup, command):
    _, project = setup
    for directory in ("paper", "examples/workspace/paper"):
        assert run(project, "pull", URL, "--dir", directory).exit_code == 0
    commit_all(project)
    head = git(project, "rev-parse", "HEAD")
    result = run(project, command, merge=False)
    assert result.exit_code != 0
    assert "more than one paper" in result.output
    assert "examples/workspace/paper, paper" in result.output
    assert "--dir" in result.output
    assert git(project, "rev-parse", "HEAD") == head
    assert not git(project, "status", "--porcelain")


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


@pytest.mark.parametrize(
    "url", ["https://example.com/x", "https://git:pw@git.overleaf.com/1", "", None]
)
def test_rejects_non_overleaf_urls(setup, url):
    _, project = setup
    result = run(project, "pull", *([url] if url is not None else []))
    assert result.exit_code != 0
    assert "git.overleaf.com/<project-id>" in result.output


@pytest.mark.parametrize(
    "interactive,caller_prompt,expected_prompt",
    [(False, None, "0"), (False, "1", "0"), (True, None, None), (True, "0", "0")],
)
def test_credentials_prompt_only_in_interactive_terminal(
    monkeypatch, interactive, caller_prompt, expected_prompt
):
    monkeypatch.delenv("OVERLEAF_TOKEN", raising=False)
    monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
    if caller_prompt is not None:
        monkeypatch.setenv("GIT_TERMINAL_PROMPT", caller_prompt)
    monkeypatch.setattr(
        module,
        "sys",
        SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: interactive)),
        raising=False,
    )
    with module.credentials() as (env, options):
        assert env.get("GIT_TERMINAL_PROMPT") == expected_prompt
        assert options == []


@pytest.mark.parametrize(
    "prompt_source", ["GIT_ASKPASS", "SSH_ASKPASS", "core.askPass"]
)
@pytest.mark.skipif(os.name == "nt", reason="POSIX askpass")
def test_unattended_missing_credentials_fail_without_prompt(
    setup, monkeypatch, prompt_source
):
    _, project = setup
    monkeypatch.delenv("OVERLEAF_TOKEN", raising=False)
    monkeypatch.delenv("GIT_ASKPASS", raising=False)
    monkeypatch.delenv("SSH_ASKPASS", raising=False)
    marker = project.parent / "prompt-ran"
    askpass = project.parent / "askpass"
    askpass.write_text(
        f'#!/bin/sh\nprintf invoked > "{marker}"\nprintf "%s\\n" fixture-password\n'
    )
    askpass.chmod(0o700)
    if prompt_source == "core.askPass":
        git(project, "config", prompt_source, str(askpass))
    else:
        monkeypatch.setenv(prompt_source, str(askpass))
    monkeypatch.setattr(
        module,
        "sys",
        SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: False)),
        raising=False,
    )
    with module.credentials() as (env, options):
        result = subprocess.run(
            ["git", *options, "-c", "credential.helper=", "credential", "fill"],
            cwd=project,
            env=env,
            input=b"url=https://git@git.overleaf.com/1234567\n\n",
            capture_output=True,
            timeout=5,
        )
    assert result.returncode != 0
    assert b"terminal prompts disabled" in result.stderr
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX askpass")
def test_interactive_credentials_keep_personal_askpass(setup, monkeypatch):
    _, project = setup
    monkeypatch.delenv("OVERLEAF_TOKEN", raising=False)
    askpass = project.parent / "askpass"
    askpass.write_text("#!/bin/sh\nprintf '%s\\n' personal-fixture\n")
    askpass.chmod(0o700)
    monkeypatch.setenv("GIT_ASKPASS", str(askpass))
    monkeypatch.setattr(
        module, "sys", SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: True))
    )
    with module.credentials() as (env, options):
        result = subprocess.run(
            ["git", *options, "-c", "credential.helper=", "credential", "fill"],
            cwd=project,
            env=env,
            input=b"url=https://git@git.overleaf.com/1234567\n\n",
            capture_output=True,
            timeout=5,
            check=True,
        )
    assert b"password=personal-fixture\n" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX askpass")
def test_token_uses_askpass_and_disables_helpers(monkeypatch):
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    assert "OVERLEAF_TOKEN" not in module.git_environment()
    with module.credentials() as (env, options):
        assert "OVERLEAF_TOKEN" not in env
        askpass = env["GIT_ASKPASS"]
        token_file = module.Path(askpass).with_name("token")
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(token_file.parent.stat().st_mode) == 0o700
        assert options == ["-c", "credential.helper="]
        answer = subprocess.run(
            [askpass, "Password for x"], env=env, capture_output=True, text=True
        )
        assert answer.stdout.strip() == "fixture-token"
        assert "fixture-token" not in open(askpass).read()
    assert not os.path.exists(askpass)
    assert not token_file.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX transport hook and askpass")
@pytest.mark.parametrize("scope", ["global", "local", "default"])
def test_transport_hooks_get_no_token_and_keep_utf8_locale(
    setup, tmp_path, monkeypatch, scope
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    hooks = project / (".git/hooks" if scope == "default" else "hooks")
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-push"
    hook.write_text(
        '#!/bin/sh\ntest -z "$OVERLEAF_TOKEN" || exit 1\n'
        'printf "%s:%s:%s" "$LC_ALL" "$LC_MESSAGES" "$LANGUAGE" > "$TEST_HOOK_MARKER"\n'
    )
    hook.chmod(0o700)
    if scope == "global":
        config = tmp_path / "gitconfig"
        config.write_text(f"[core]\n\thooksPath = {hooks}\n")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    elif scope == "local":
        git(project, "config", "core.hooksPath", "hooks")
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("LC_MESSAGES", "C.UTF-8")
    monkeypatch.setenv("LANGUAGE", "fixture-language")
    marker = tmp_path / "transport-hook-ran"
    monkeypatch.setenv("TEST_HOOK_MARKER", str(marker))
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert marker.read_text() == "C.UTF-8:C.UTF-8:fixture-language"
    git(seed, "fetch", "-q", "origin")
    assert git(seed, "show", "origin/master:main.tex") == "reviewed edit"


@pytest.mark.skipif(os.name == "nt", reason="POSIX pre-push hook")
@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_honors_workspace_pre_push_failure(setup, dry_run):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    before = (project / ".asta/overleaf/paper.json").read_bytes()
    remote_before = git(seed, "rev-parse", "origin/master")
    hooks = project / "hooks"
    hooks.mkdir()
    hook = hooks / "pre-push"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o700)
    git(project, "config", "core.hooksPath", "hooks")
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert (result.exit_code == 0) == dry_run, result.output
    if not dry_run:
        assert "Also check workspace pre-push hooks" in result.output
    assert (project / ".asta/overleaf/paper.json").read_bytes() == before
    assert git(seed, "ls-remote", "origin", "master").split()[0] == remote_before


@pytest.mark.skipif(os.name == "nt", reason="POSIX commit hook and askpass")
@pytest.mark.parametrize("scope", ["global", "local", "default"])
def test_publish_keeps_token_out_of_commit_hooks(setup, tmp_path, monkeypatch, scope):
    seed, project = setup
    monkeypatch.delenv("GIT_ASKPASS", raising=False)
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    hooks = project / (".git/hooks" if scope == "default" else "hooks")
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        'test -z "$OVERLEAF_TOKEN" || exit 1\n'
        'test -z "$GIT_ASKPASS" || exit 1\n'
        'printf checked > "$TEST_HOOK_MARKER"\n'
    )
    hook.chmod(0o700)
    if scope == "global":
        config = tmp_path / "gitconfig"
        config.write_text(f"[core]\n\thooksPath = {hooks}\n")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    elif scope == "local":
        git(project, "config", "core.hooksPath", "hooks")
    marker = tmp_path / "hook-ran"
    monkeypatch.setenv("TEST_HOOK_MARKER", str(marker))
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert marker.read_text() == "checked"
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "reviewed edit\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX commit hook")
@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_honors_workspace_hook_failure(setup, dry_run):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    before = (project / ".asta/overleaf/paper.json").read_bytes()
    remote_before = git(seed, "rev-parse", "origin/master")
    hook = project / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o700)
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert (result.exit_code == 0) == dry_run, result.output
    if not dry_run:
        assert "commit hooks and signing settings" in result.output
        assert "not the full workspace" in result.output
    assert (project / ".asta/overleaf/paper.json").read_bytes() == before
    assert git(seed, "ls-remote", "origin", "master").split()[0] == remote_before


@pytest.mark.skipif(
    os.name == "nt", reason="SSH signing integration is tested on POSIX"
)
@pytest.mark.parametrize(
    "relative_key,relative_program",
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_publish_honors_workspace_signing(
    setup, tmp_path, relative_key, relative_program
):
    seed, project = setup
    version = re.search(r"(\d+)\.(\d+)", git(project, "--version"))
    if (
        not shutil.which("ssh-keygen")
        or not version
        or tuple(map(int, version.groups())) < (2, 34)
    ):
        pytest.skip("SSH commit signing requires ssh-keygen and Git >= 2.34")
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    key = project / ".git/signing-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    git(project, "config", "commit.gpgsign", "true")
    git(project, "config", "gpg.format", "ssh")
    git(
        project,
        "config",
        "user.signingkey",
        str(key.relative_to(project)) if relative_key else str(key),
    )
    if relative_program:
        program = project / ".git/sign-paper"
        program.write_text('#!/bin/sh\nexec ssh-keygen "$@"\n')
        program.chmod(0o700)
        git(project, "config", "gpg.ssh.program", str(program.relative_to(project)))
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "fetch", "-q", "origin")
    allowed = tmp_path / "allowed-signers"
    allowed.write_text("t@t " + key.with_suffix(".pub").read_text())
    git(
        seed,
        "-c",
        f"gpg.ssh.allowedSignersFile={allowed}",
        "verify-commit",
        "origin/master",
    )


@pytest.mark.parametrize(
    "signing_format,key",
    [
        ("openpgp", "ABCD1234"),
        ("openpgp", "keys/signing-key"),
        ("x509", "certificates/signing-key"),
        ("ssh", "key::ssh-ed25519 fixture"),
        ("ssh", "ssh-ed25519 fixture"),
    ],
)
def test_commit_settings_preserves_key_identifiers_and_path_commands(
    setup, signing_format, key
):
    _, project = setup
    git(project, "config", "gpg.format", signing_format)
    git(project, "config", "user.signingkey", key)
    git(project, "config", "gpg.program", "gpg")
    options = module.commit_settings(project)
    assert f"user.signingkey={key}" in options
    assert "gpg.program=gpg" in options


@pytest.mark.parametrize("command", ["pull", "publish"])
@pytest.mark.parametrize("directory", [".git", ".git/objects", "paper/../.git", ".GIT"])
def test_sync_refuses_git_directory(setup, monkeypatch, command, directory):
    _, project = setup
    before = git(project, "rev-parse", "HEAD")
    config = (project / ".git/config").read_bytes()
    monkeypatch.setattr(module, "clone", lambda *a: pytest.fail("must not clone"))
    result = run(
        project, command, *([URL] if command == "pull" else []), "--dir", directory
    )
    assert result.exit_code != 0 and "unsafe path" in result.output
    assert git(project, "rev-parse", "HEAD") == before
    assert (project / ".git/config").read_bytes() == config
    assert not (project / ".git/overleaf.json").exists()


@pytest.mark.parametrize("command", ["pull", "publish"])
@pytest.mark.parametrize("directory", ["admin", "admin/objects", "private"])
def test_sync_refuses_separate_git_directory(setup, monkeypatch, command, directory):
    _, project = setup
    metadata = project / "private/admin"
    metadata.parent.mkdir()
    (project / ".git").rename(metadata)
    (project / ".git").write_text("gitdir: private/admin\n")
    directory = "private/" + directory if directory != "private" else directory
    before = git(project, "rev-parse", "HEAD")
    config = (metadata / "config").read_bytes()
    monkeypatch.setattr(module, "clone", lambda *a: pytest.fail("must not clone"))
    result = run(
        project, command, *([URL] if command == "pull" else []), "--dir", directory
    )
    assert result.exit_code != 0 and "Git administrative" in result.output
    assert git(project, "rev-parse", "HEAD") == before
    assert (metadata / "config").read_bytes() == config
    assert not (metadata / "overleaf.json").exists()


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_refuses_absolute_directory(setup, monkeypatch, command):
    _, project = setup
    monkeypatch.setattr(module, "clone", lambda *a: pytest.fail("must not clone"))
    result = run(
        project,
        command,
        *([URL] if command == "pull" else []),
        "--dir",
        str(project / "paper"),
    )
    assert result.exit_code != 0
    assert "--dir must be relative to the workspace" in result.output
    assert not (project / "paper").exists()


@pytest.mark.parametrize("command", ["pull", "publish"])
@pytest.mark.parametrize("directory", ["paper", "linked/paper"])
def test_sync_refuses_symlinked_paper_directory(setup, monkeypatch, directory, command):
    _, project = setup
    target = project / "actual"
    target.mkdir()
    marker = target / "keep.tex"
    marker.write_text("keep this\n")
    link = project / directory.split("/")[0]
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(module, "clone", lambda *a: pytest.fail("must not clone"))
    result = run(
        project, command, *([URL] if command == "pull" else []), "--dir", directory
    )
    assert result.exit_code != 0 and "symlinked directory" in result.output
    assert marker.read_text() == "keep this\n"
    assert list(target.iterdir()) == [marker]


@pytest.mark.parametrize(
    "names",
    [["caf\u00e9.tex", "cafe\u0301.tex"], ["caf\u00e9/a.tex", "cafe\u0301/b.tex"]],
)
def test_refuses_unicode_normalization_collisions(names):
    with pytest.raises(module.click.ClickException, match="Unicode normalization"):
        module.check_paths(names)


def test_pull_reports_unborn_overleaf_project(setup):
    seed, project = setup
    git(
        seed,
        "--git-dir",
        str(seed.parent / "overleaf.git"),
        "update-ref",
        "-d",
        "refs/heads/master",
    )
    result = run(project, "pull", URL)
    assert result.exit_code != 0 and "Overleaf project has no commits" in result.output
    assert not (project / "paper").exists()


def test_pull_refuses_a_different_project_before_cloning(setup, monkeypatch):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    before = {path.name: path.read_bytes() for path in paper.iterdir()}
    monkeypatch.setattr(module, "clone", lambda *a: pytest.fail("must not clone"))
    result = run(project, "pull", "https://git.overleaf.com/7654321")
    assert result.exit_code != 0
    assert "another Overleaf project" in result.output
    assert {path.name: path.read_bytes() for path in paper.iterdir()} == before


@pytest.mark.parametrize(
    "url", [URL + "/", URL + ".git", URL.replace("https://", "https://git@")]
)
def test_pull_accepts_the_same_project_url(setup, url):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    result = run(project, "pull", url)
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("remote_text", ["remote edit\n", None])
def test_pull_handles_committed_workspace_modify_delete_and_text_conflicts(
    setup, remote_text
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text("reviewed workspace edit\n")
    commit_all(project)
    before = (project / ".asta/overleaf/paper.json").read_bytes()
    overleaf_edit(seed, "main.tex", remote_text)
    result = run(project, "pull")
    if remote_text is None:
        assert result.exit_code != 0 and "disagree on whether main.tex" in result.output
        assert (project / "paper/main.tex").read_text() == "reviewed workspace edit\n"
        assert (project / ".asta/overleaf/paper.json").read_bytes() == before
        assert not git(project, "status", "--porcelain")
        return
    assert result.exit_code == CONFLICT_EXIT, result.output
    merged = (project / "paper/main.tex").read_text()
    assert "<<<<<<< workspace\nreviewed workspace edit\n" in merged
    assert "remote edit\n>>>>>>> overleaf\n" in merged
    assert "main.tex" in result.output
    publish = run(project, "publish")
    assert publish.exit_code != 0


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
    assert "main.tex was added independently on both sides" in result.output
    assert (project / "paper/main.tex").read_text() == "existing paper\n"
    assert not (project / ".asta/overleaf/paper.json").exists()


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
    # Set the tracked mode explicitly; Windows cannot express POSIX execute bits.
    if os.name != "nt":
        (repo / name).chmod(0o755)
    git(repo, "update-index", "--chmod=+x", name)
    git(repo, "commit", "-m", "executable")
    if command == "pull":
        git(seed, "push", "-q", "origin", "master")
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, command)
    assert result.exit_code != 0 and "executable" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize(
    "name",
    [
        "../escape.tex",
        ".git/config",
        "nested/.Git/config",
        ".g\u200cit/config",
        "nested/GIT~1/config",
        ".git./config",
        ".git /config",
        ".git::$INDEX_ALLOCATION/config",
        r".git\config",
        r"nested\.git\config",
        "/absolute",
    ],
)
def test_pull_refuses_unsafe_remote_tree_paths(setup, monkeypatch, name):
    _, project = setup
    real = module.tree
    monkeypatch.setattr(
        module,
        "tree",
        lambda repo, revision, prefix="": (
            {name: next(iter(real(repo, revision, prefix).values()))}
            if repo.name == "overleaf"
            else real(repo, revision, prefix)
        ),
    )
    result = run(project, "pull", URL)
    assert result.exit_code != 0 and "unsafe path" in result.output
    assert not (project / "paper").exists()
    assert not (project / "escape.tex").exists()


@pytest.mark.parametrize(
    "name",
    [
        "line\nbreak.tex",
        "tab\tname.tex",
        "escape\x1b[2J.tex",
        "delete\x7f.tex",
        "control\x9b.tex",
    ],
)
def test_pull_refuses_control_characters_before_deletions(setup, monkeypatch, name):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    overleaf_edit(seed, "old.tex", None)
    paper = project / "paper"
    before = {p.name: p.read_bytes() for p in paper.iterdir()}
    real = module.tree

    def remote_tree(repo, revision, prefix=""):
        entries = real(repo, revision, prefix)
        if repo.name == "overleaf":
            entries[name] = ("100644", "unused")
        return entries

    monkeypatch.setattr(module, "tree", remote_tree)
    result = run(project, "pull")
    assert result.exit_code != 0 and "unsafe path" in result.output
    assert repr(name) in result.output
    assert not any(
        ord(c) < 32 and c != "\n" or 127 <= ord(c) <= 159 for c in result.output
    )
    assert {p.name: p.read_bytes() for p in paper.iterdir()} == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_pull_refuses_ignored_symlink_config(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    config = project / ".asta/overleaf/paper.json"
    outside = project.parent / "outside.json"
    outside.write_bytes(config.read_bytes())
    config.unlink()
    os.symlink(outside, config)
    git(project, "rm", "--cached", "--ignore-unmatch", ".asta/overleaf/paper.json")
    (project / ".gitignore").write_text("/.asta/overleaf/paper.json\n")
    commit_all(project)
    before = outside.read_bytes()
    result = run(project, "pull")
    assert result.exit_code != 0 and "symlink" in result.output
    assert outside.read_bytes() == before


@pytest.mark.parametrize(
    "setting",
    [
        "autocrlf",
        pytest.param(
            "filter",
            marks=pytest.mark.skipif(os.name == "nt", reason="POSIX sed filter"),
        ),
        pytest.param(
            "hook",
            marks=pytest.mark.skipif(os.name == "nt", reason="POSIX commit hook"),
        ),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_refuses_git_content_rewriting(setup, monkeypatch, setting, dry_run):
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
    metadata = (project / ".asta/overleaf/paper.json").read_bytes()
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    if setting == "hook" and dry_run:
        assert (
            result.exit_code == 0
            and "commit hooks and signing were not run" in result.output
        )
        assert git(seed, "ls-remote", "origin", "master") == before
        return
    assert result.exit_code != 0 and "nothing pushed" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / ".asta/overleaf/paper.json").read_bytes() == metadata
    assert source.read_bytes() == b"reviewed\r\n"


@pytest.mark.parametrize("ignore_source", ["root", "paper", "info", "global"])
def test_pull_refuses_ignored_imports_before_deleting_or_updating(setup, ignore_source):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    pattern = "*.png\n"
    if ignore_source == "root":
        (project / ".gitignore").write_text(pattern)
        commit_all(project)
    elif ignore_source == "paper":
        (project / "paper/.gitignore").write_text(pattern)
        commit_all(project)
    elif ignore_source == "info":
        (project / ".git/info/exclude").write_text(pattern)
    else:
        excludes = project.parent / "excludes"
        excludes.write_text(pattern)
        git(project, "config", "core.excludesFile", str(excludes))
    before = (project / ".asta/overleaf/paper.json").read_bytes()
    overleaf_edit(seed, "old.tex", None)
    overleaf_edit(seed, "figure.png", "remote figure\n")
    result = run(project, "pull")
    assert result.exit_code != 0 and "paper/figure.png is ignored" in result.output
    assert "Adjust the ignore rules" in result.output
    assert not (project / "paper/figure.png").exists()
    assert (project / "paper/old.tex").read_text() == "old\n"
    assert (project / ".asta/overleaf/paper.json").read_bytes() == before
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("pattern", ["/paper/", "/.asta/overleaf/paper.json"])
def test_pull_refuses_ignored_first_import_and_metadata(setup, pattern):
    _, project = setup
    (project / ".gitignore").write_text(pattern + "\n")
    commit_all(project)
    result = run(project, "pull", URL)
    assert result.exit_code != 0 and "is ignored" in result.output
    assert not (project / "paper").exists()


def test_pull_updates_tracked_files_even_when_ignore_pattern_matches(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / ".gitignore").write_text("*.tex\n")
    commit_all(project)
    overleaf_edit(seed, "main.tex", "remote edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper/main.tex").read_text() == "remote edit\n"


@pytest.mark.parametrize("name", [".gitignore", "nested/.gitignore"])
def test_pull_refuses_remote_ignore_rules_before_writing(setup, name):
    seed, project = setup
    if "/" in name:
        (seed / "nested").mkdir()
    overleaf_edit(seed, name, "valuable remote content\n")
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "pull", URL)
    assert result.exit_code != 0
    assert name in result.output
    assert not (project / "paper").exists()
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize(
    "name",
    ["overleaf.json", "Overleaf.json", "overleaf.jſon", "Overleaf.json/content.tex"],
)
@pytest.mark.parametrize("existing_paper", [False, True])
def test_paper_files_named_overleaf_json_round_trip(setup, name, existing_paper):
    seed, project = setup
    if existing_paper:
        assert run(project, "pull", URL).exit_code == 0
        commit_all(project)
    (seed / name).parent.mkdir(parents=True, exist_ok=True)
    overleaf_edit(seed, name, "ordinary paper content\n")

    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    source = project / "paper" / name
    assert source.read_text() == "ordinary paper content\n"
    assert module.load_config(project / "paper")["url"] == URL
    source.write_text("reviewed paper content\n")
    commit_all(project)
    assert module.paper_files(project, "HEAD", "paper/")[name] == source.read_bytes()

    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "--ff-only")
    assert (seed / name).read_bytes() == source.read_bytes()
    assert module.paper_files(seed, "HEAD")[name] == source.read_bytes()
    # A later pull must count this publication with the JSON source included.
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert "record not used" not in result.output


@pytest.mark.parametrize(
    "bibliographies", [[], ["citations.bib"], ["references.bib", "extra.bib"]]
)
def test_roundtrip_preserves_arbitrary_latex_layout_without_root_bibliography(
    setup, bibliographies
):
    seed, project = setup
    git(seed, "rm", "references.bib", "main.tex")
    (seed / "manuscript.tex").write_text("\\documentclass{article}\noriginal\n")
    (seed / "styles").mkdir()
    (seed / "styles/custom.cls").write_text("custom class\n")
    for name in bibliographies:
        (seed / name).write_text("@misc{remote_entry}\n")
    commit_all(seed)
    git(seed, "push", "origin", "master")
    git(project, "rm", "references.bib")
    commit_all(project)
    assert run(project, "pull", URL).exit_code == 0
    expected = {
        name: module.git_bytes("show", f"HEAD:{name}", cwd=seed)
        for name in module.tree(seed, "HEAD")
    }
    for name, data in expected.items():
        assert (project / "paper" / name).read_bytes() == data
    (project / "paper/manuscript.tex").write_text("reviewed edit\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "origin", "master")
    expected["manuscript.tex"] = b"reviewed edit\n"
    assert module.read_plain_files(seed, "HEAD") == expected


def test_bibliography_overlapping_edits_get_conflict_markers(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/references.bib").write_text("@misc{workspace_edit}\n")
    commit_all(project)
    overleaf_edit(seed, "references.bib", "@misc{collaborator}\n")
    result = run(project, "pull")
    assert result.exit_code == CONFLICT_EXIT, result.output
    assert "same lines in: references.bib" in result.output
    assert "Resolve conflicts, review with `git diff`" in result.output
    merged = (project / "paper/references.bib").read_text()
    assert "<<<<<<< workspace\n@misc{workspace_edit}\n" in merged
    assert "@misc{collaborator}\n>>>>>>> overleaf\n" in merged


@pytest.mark.parametrize(
    "name",
    ["main.tex", "references.bib", "custom.sty", "custom.cls", "notes.txt", "notes.md"],
)
def test_pull_merges_non_overlapping_edits(setup, name):
    seed, project = setup
    overleaf_edit(seed, name, "one\ntwo\nthree\nfour\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper" / name).write_text("ONE\ntwo\nthree\nfour\n")
    commit_all(project)
    overleaf_edit(seed, name, "one\ntwo\nthree\nFOUR\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert "same lines" not in result.output
    assert (project / "paper" / name).read_text() == "ONE\ntwo\nthree\nFOUR\n"


@pytest.mark.parametrize(
    "name,header",
    [
        ("figure.pdf", "%PDF-1.4\n"),
        ("figure.eps", "%!PS-Adobe-3.0\n"),
        ("figure.svg", "<svg>\n"),
        ("figure.png", ""),
        ("figure.xlsx", ""),
        ("main.tex", "\0"),
    ],
)
def test_pull_refuses_concurrent_asset_edits_without_writing(setup, name, header):
    seed, project = setup
    overleaf_edit(seed, name, header + "one\ntwo\nthree\nfour\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    (paper / name).write_text(header + "ONE\ntwo\nthree\nfour\n")
    commit_all(project)
    before = {p.name: p.read_bytes() for p in paper.iterdir()}
    overleaf_edit(seed, name, header + "one\ntwo\nthree\nFOUR\n")
    overleaf_edit(seed, "old.tex", None)
    overleaf_edit(seed, "new.tex", "new source\n")

    result = run(project, "pull")

    assert result.exit_code != 0, result.output
    assert name in result.output and "nothing copied" in result.output
    assert {p.name: p.read_bytes() for p in paper.iterdir()} == before
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("side", ["workspace", "overleaf"])
def test_pull_preserves_one_sided_asset_edits(setup, side):
    seed, project = setup
    overleaf_edit(seed, "figure.pdf", "%PDF-1.4\noriginal\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    changed = "%PDF-1.4\nchanged\n"
    if side == "workspace":
        (project / "paper/figure.pdf").write_text(changed)
        commit_all(project)
        overleaf_edit(seed, "main.tex", "remote source edit\n")
    else:
        overleaf_edit(seed, "figure.pdf", changed)

    result = run(project, "pull")

    assert result.exit_code == 0, result.output
    assert (project / "paper/figure.pdf").read_text() == changed


def test_publish_refuses_unresolved_conflict_markers(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text(
        "<<<<<<< workspace\nours\n=======\ntheirs\n>>>>>>> overleaf\n"
    )
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "Unresolved conflict markers in: main.tex" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_pull_after_publish_starts_from_published_commit(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    record = (project / ".asta/overleaf/paper.json").read_bytes()
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert (project / ".asta/overleaf/paper.json").read_bytes() == record
    assert not git(project, "status", "--porcelain")
    published_source = git(project, "rev-parse", "HEAD")
    git(seed, "pull", "-q", "origin", "master")
    assert git(seed, "log", "-1", "--format=%s") == (
        f"Publish workspace commit {published_source}"
    )
    again = run(project, "publish")
    assert again.exit_code == 0 and "already matches" in again.output
    assert not git(project, "status", "--porcelain")
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert "same lines" not in result.output
    assert (project / "paper/main.tex").read_text() == "collaborator edit\n"


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("followup", [False, True])
@pytest.mark.parametrize("local_edit", [None, "separate-line", "same-line"])
def test_pull_into_older_checkout_imports_published_edits(setup, followup, local_edit):
    seed, project = setup
    overleaf_edit(seed, "main.tex", "one\ntwo\nthree\nfour\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    stale = project.parent / "stale"
    git(
        project.parent,
        "clone",
        "--no-local",
        git(project, "remote", "get-url", "origin"),
        str(stale),
    )
    if local_edit:
        (stale / "paper/main.tex").write_text(
            "one\ntwo\nthree\nFOUR\n"
            if local_edit == "separate-line"
            else "local\ntwo\nthree\nfour\n"
        )
        commit_all(stale)
    (project / "paper/main.tex").write_text("published\ntwo\nthree\nfour\n")
    (project / "paper/added.tex").write_text("published addition\n")
    git(project, "rm", "paper/old.tex")
    commit_all(project)
    source = git(project, "rev-parse", "HEAD")
    assert run(project, "publish").exit_code == 0
    if followup:
        overleaf_edit(seed, "references.bib", "@misc{followup}\n")
    remote_head = git(seed, "ls-remote", "origin", "master").split()[0]
    before_refs = git(stale, "show-ref")
    assert (
        subprocess.run(
            ["git", "cat-file", "-e", source], cwd=stale, capture_output=True
        ).returncode
        != 0
    )

    result = run(stale, "pull")

    content = (stale / "paper/main.tex").read_text()
    if local_edit == "same-line":
        assert result.exit_code == CONFLICT_EXIT, result.output
        assert "same lines" in result.output
        assert (
            content
            == "<<<<<<< workspace\nlocal\n=======\npublished\n>>>>>>> overleaf\ntwo\nthree\nfour\n"
        )
    else:
        assert result.exit_code == 0, result.output
        assert "same lines" not in result.output
        assert content == (
            "published\ntwo\nthree\nFOUR\n"
            if local_edit
            else "published\ntwo\nthree\nfour\n"
        )
    assert (stale / "paper/added.tex").read_text() == "published addition\n"
    assert not (stale / "paper/old.tex").exists()
    assert (stale / "paper/references.bib").read_bytes() == (
        b"@misc{followup}\n"
        if followup
        else (project / "paper/references.bib").read_bytes()
    )
    assert (
        json.loads((stale / ".asta/overleaf/paper.json").read_text())["base"]
        == remote_head
    )
    assert git(stale, "diff", "--", "paper/main.tex")
    assert git(stale, "show-ref") == before_refs


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_pull_preserves_local_revert_of_ancestor_publication(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    original = (project / "paper/main.tex").read_bytes()
    (project / "paper/main.tex").write_text("published edit\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    (project / "paper/main.tex").write_bytes(original)
    commit_all(project)

    result = run(project, "pull")

    assert result.exit_code == 0, result.output
    assert "same lines" not in result.output
    assert (project / "paper/main.tex").read_bytes() == original


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_unmerged_publication_marker_does_not_bypass_review(setup, command):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    git(project, "switch", "-q", "-c", "unreviewed")
    (project / "paper/main.tex").write_text("unreviewed Overleaf edit\n")
    commit_all(project)
    source = git(project, "rev-parse", "HEAD")
    git(project, "switch", "-q", "main")
    (seed / "main.tex").write_text("unreviewed Overleaf edit\n")
    git(seed, "add", "main.tex")
    git(seed, "commit", "-q", "-m", f"Publish workspace commit {source}")
    git(seed, "push", "-q", "origin", "master")
    before = git(seed, "ls-remote", "origin", "master")

    result = run(project, command, merge=False)

    assert git(seed, "ls-remote", "origin", "master") == before
    if command == "publish":
        assert result.exit_code != 0 and "changed since the last sync" in result.output
        assert not git(project, "status", "--porcelain")
    else:
        assert result.exit_code == 0, result.output
        assert (project / "paper/main.tex").read_text() == "unreviewed Overleaf edit\n"
        assert git(project, "diff", "--", "paper/main.tex")


@pytest.mark.parametrize("newest", [True, False])
def test_empty_overleaf_subjects_are_ordinary_edits(setup, newest):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    git(seed, "pull", "-q", "origin", "master")
    (seed / "main.tex").write_text("collaborator edit\n")
    git(seed, "commit", "-q", "-a", "--allow-empty-message", "-m", "")
    if not newest:
        overleaf_edit(seed, "old.tex", "later edit\n")
    git(seed, "push", "-q", "origin", "HEAD:master")
    before_remote = git(seed, "ls-remote", "origin", "master")

    result = run(project, "publish")

    assert result.exit_code == 1 and "Overleaf has changed" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before_remote
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert (project / "paper/main.tex").read_text() == "collaborator edit\n"


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("rewrite", ["subject", "extra-commit"])
def test_unrecognized_git_integration_history_requires_pull_and_review(setup, rewrite):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    git(seed, "pull", "-q", "origin", "master")
    if rewrite == "subject":
        git(seed, "commit", "--amend", "-m", "Update on Overleaf")
    else:
        tree = git(seed, "rev-parse", "HEAD^{tree}")
        head = git(seed, "rev-parse", "HEAD")
        version = git(seed, "commit-tree", tree, "-p", head, "-m", "Update on Overleaf")
        git(seed, "reset", "--hard", version)
    git(seed, "push", "-q", "--force", "origin", "HEAD:master")
    before_remote = git(seed, "ls-remote", "origin", "master")
    before_record = (project / ".asta/overleaf/paper.json").read_bytes()

    result = run(project, "publish")

    assert result.exit_code == 1, result.output
    if rewrite == "subject":
        assert "Overleaf sync record not used" in result.output
    assert "Overleaf has changed" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before_remote
    assert (project / ".asta/overleaf/paper.json").read_bytes() == before_record
    assert not git(project, "status", "--porcelain")
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert (project / "paper/main.tex").read_text() == "reviewed publication\n"
    assert git(project, "diff", "--name-only") == ".asta/overleaf/paper.json"
    assert json.loads((project / ".asta/overleaf/paper.json").read_text())[
        "base"
    ] == git(seed, "rev-parse", "HEAD")


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize("command", ["pull", "publish", "dry-run"])
@pytest.mark.parametrize("depth", [1, 2])
def test_shallow_sync_accepts_record_source_at_default_tip(
    setup, published, command, depth
):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed paper\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    if published:
        assert run(project, "publish", merge=False).exit_code == 0
    shallow = project.parent / "shallow"
    git(
        project.parent,
        "clone",
        f"--depth={depth}",
        (project.parent / "workspace.git").as_uri(),
        str(shallow),
    )
    shallow_file = shallow / git(shallow, "rev-parse", "--git-path", "shallow")
    before_shallow = shallow_file.read_bytes()
    before_refs = git(shallow, "show-ref")
    fetch_head = shallow / git(shallow, "rev-parse", "--git-path", "FETCH_HEAD")
    before_fetch = fetch_head.read_bytes() if fetch_head.exists() else None
    args = ("publish", "--dry-run") if command == "dry-run" else (command,)

    result = run(shallow, *args, merge=False)

    # No historical base-move proof is required. A record at the visible
    # default tip already proves membership even in a depth-one checkout.
    assert result.exit_code == 0, result.output
    assert shallow_file.read_bytes() == before_shallow
    assert git(shallow, "show-ref") == before_refs
    assert (fetch_head.read_bytes() if fetch_head.exists() else None) == before_fetch
    assert git(shallow, "diff", "--name-only") == (
        ".asta/overleaf/paper.json" if command == "pull" and published else ""
    )
    assert git(shallow, "status", "--porcelain") == (
        "M .asta/overleaf/paper.json" if command == "pull" and published else ""
    )


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("source_present", [False, True])
@pytest.mark.parametrize("command", ["pull", "publish", "dry-run"])
def test_sync_refuses_incomplete_shallow_record_verification(
    setup, tmp_path, source_present, command
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    original = (project / "paper/main.tex").read_bytes()
    config = (project / ".asta/overleaf/paper.json").read_bytes()
    (project / "paper/main.tex").write_text("reviewed publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    source = git(project, "rev-parse", "HEAD")
    # A reviewed revert intentionally restores the last pull's bytes, while
    # Overleaf still holds the published edit. Falling back to base undoes it.
    (project / "paper/main.tex").write_bytes(original)
    commit_all(project)
    git(project, "push", "origin", "main")
    shallow = tmp_path / "shallow"
    git(
        tmp_path,
        "clone",
        "--depth=1",
        (tmp_path / "workspace.git").as_uri(),
        str(shallow),
    )
    git(shallow, "config", "user.name", "t")
    git(shallow, "config", "user.email", "t@t")
    if source_present:
        # Having the object does not prove ancestry through a shallow boundary.
        git(shallow, "fetch", "--no-write-fetch-head", "origin", source)
    assert (module.resolve_commit(shallow, source) is not None) == source_present
    if source_present:
        assert not module.is_ancestor(shallow, source, "HEAD")
    shallow_file = shallow / git(shallow, "rev-parse", "--git-path", "shallow")
    before_shallow = shallow_file.read_bytes()
    before_refs = git(shallow, "show-ref")
    fetch_head = shallow / git(shallow, "rev-parse", "--git-path", "FETCH_HEAD")
    fetch_head.write_bytes(b"existing fetch state\n")
    before = {p.name: p.read_bytes() for p in (shallow / "paper").iterdir()}
    remote = git(seed, "ls-remote", "origin", "master")
    record = origin_record(tmp_path)
    args = ("publish", "--dry-run") if command == "dry-run" else (command,)

    result = run(shallow, *args, merge=False)

    assert result.exit_code == 1, result.output
    assert "shallow workspace history" in result.output
    assert (
        "nothing copied" if command == "pull" else "nothing pushed"
    ) in result.output
    assert {p.name: p.read_bytes() for p in (shallow / "paper").iterdir()} == before
    assert shallow_file.read_bytes() == before_shallow
    assert git(shallow, "show-ref") == before_refs
    assert fetch_head.read_bytes() == b"existing fetch state\n"
    assert git(seed, "ls-remote", "origin", "master") == remote
    assert origin_record(tmp_path) == record
    assert not git(shallow, "status", "--porcelain")
    assert not git(shallow, "for-each-ref", "refs/asta")

    # Fetching history is an explicit user action; a retry preserves the revert.
    git(shallow, "fetch", "--unshallow", "origin")
    retried = run(shallow, *args, merge=False)
    assert retried.exit_code == 0, retried.output
    assert (shallow / "paper/main.tex").read_bytes() == original
    if command == "pull":
        assert git(shallow, "diff", "--name-only") == ".asta/overleaf/paper.json"
    else:
        assert (shallow / ".asta/overleaf/paper.json").read_bytes() == config


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_pull_refuses_hidden_checkout_ancestry_even_when_record_is_reviewed(
    setup, tmp_path
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    original = (project / "paper/main.tex").read_bytes()
    (project / "paper/main.tex").write_text("reviewed publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    source = git(project, "rev-parse", "HEAD")
    (project / "paper/main.tex").write_bytes(original)
    commit_all(project)
    git(project, "push", "origin", "main")
    shallow = tmp_path / "shallow"
    git(
        tmp_path,
        "clone",
        "--depth=1",
        (tmp_path / "workspace.git").as_uri(),
        str(shallow),
    )
    # A parallel documentation branch makes the source reachable from the new
    # default tip, while the checkout's own shallow boundary still hides it.
    git(project, "checkout", "-b", "parallel", source)
    (project / "README.md").write_text("unrelated documentation\n")
    commit_all(project)
    git(project, "checkout", "main")
    git(project, "merge", "--no-ff", "parallel", "-m", "Merge documentation")
    git(project, "push", "origin", "main")
    with module.default_branch(shallow) as (default, _):
        assert module.is_ancestor(shallow, source, default)
        assert not module.is_ancestor(shallow, source, "HEAD")
    before = {p.name: p.read_bytes() for p in (shallow / "paper").iterdir()}
    shallow_file = shallow / git(shallow, "rev-parse", "--git-path", "shallow")
    before_shallow = shallow_file.read_bytes()
    before_refs = git(shallow, "show-ref")
    fetch_head = shallow / git(shallow, "rev-parse", "--git-path", "FETCH_HEAD")
    fetch_head.write_bytes(b"existing fetch state\n")
    remote = git(seed, "ls-remote", "origin", "master")
    record = origin_record(tmp_path)

    result = run(shallow, "pull", merge=False)

    assert result.exit_code == 1, result.output
    assert "shallow workspace history" in result.output
    assert "nothing copied" in result.output
    assert {p.name: p.read_bytes() for p in (shallow / "paper").iterdir()} == before
    assert shallow_file.read_bytes() == before_shallow
    assert git(shallow, "show-ref") == before_refs
    assert fetch_head.read_bytes() == b"existing fetch state\n"
    assert git(seed, "ls-remote", "origin", "master") == remote
    assert origin_record(tmp_path) == record
    assert not git(shallow, "for-each-ref", "refs/asta")
    assert not git(shallow, "status", "--porcelain")
    git(shallow, "fetch", "--unshallow", "origin")
    retried = run(shallow, "pull", merge=False)
    assert retried.exit_code == 0, retried.output
    assert (shallow / "paper/main.tex").read_bytes() == original
    assert git(shallow, "diff", "--name-only") == ".asta/overleaf/paper.json"


@pytest.mark.parametrize("style", ["merge", "diff3", "zdiff3"])
@pytest.mark.parametrize("scope", ["caller", "global"])
def test_merge_conflict_style_is_independent_of_caller_config(
    setup, monkeypatch, style, scope
):
    _, project = setup
    if scope == "caller":
        git(project, "config", "merge.conflictStyle", style)
    else:
        config = project.parent / "global-config"
        git(project, "config", "--file", str(config), "merge.conflictStyle", style)
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.chdir(project)

    content, clean = module.merge_text("main.tex", b"ours\n", b"base\n", b"theirs\n")

    assert not clean
    assert content == b"<<<<<<< workspace\nours\n=======\ntheirs\n>>>>>>> overleaf\n"
    clean_content, clean = module.merge_text(
        "main.tex", b"ONE\ntwo\nthree\n", b"one\ntwo\nthree\n", b"one\ntwo\nTHREE\n"
    )
    assert clean and clean_content == b"ONE\ntwo\nTHREE\n"


@pytest.mark.parametrize(
    "name,data",
    [
        (
            "figure.pdf",
            b"%PDF-1.4\n<<<<<<< workspace\nexample\n=======\nexample\n>>>>>>> overleaf\n",
        ),
        ("figure.png", b"\x89PNG\0\n<<<<<<< workspace\n=======\n>>>>>>> overleaf\n"),
        (
            "main.tex",
            b"verbatim example:\n<<<<<<< documentation\n=======\n>>>>>>> documentation\n",
        ),
        ("notes.md", b"<<<<<<< HEAD\nan isolated example marker\n"),
        ("binary.txt", b"\0\n<<<<<<< workspace\n=======\n>>>>>>> overleaf\n"),
    ],
)
def test_publish_allows_assets_and_unrelated_marker_examples(setup, name, data):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / name).write_bytes(data)
    commit_all(project)

    result = run(project, "publish")

    assert result.exit_code == 0, result.output
    assert not git(project, "status", "--porcelain")
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / name).read_bytes() == data


@pytest.mark.parametrize(
    "marker", ["<<<<<<< workspace", "||||||| last sync", ">>>>>>> overleaf"]
)
def test_publish_refuses_partial_generated_conflicts(setup, marker):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text(marker + "\npartial resolution\n")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "Unresolved conflict markers in: main.tex" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("exit_code", [128, 255, -9])
def test_pull_reports_merge_failure_without_copying_or_leaking_diagnostics(
    setup, monkeypatch, exit_code
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("workspace edit\n")
    commit_all(project)
    overleaf_edit(seed, "main.tex", "remote edit\n")
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    real = module.subprocess.run

    def fail_merge(args, **kwargs):
        if args[0] == "git" and "merge-file" in args:
            return subprocess.CompletedProcess(
                args, exit_code, b"partial output", b"fixture-secret"
            )
        return real(args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", fail_merge)
    result = run(project, "pull")

    assert result.exit_code != 0
    assert f"git merge-file failed (exit {exit_code})" in result.output
    assert "fixture-secret" not in result.output
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before
    assert not git(project, "status", "--porcelain")


def test_publish_explains_reset_overleaf_history_without_pushing(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(seed, "switch", "--orphan", "reset")
    (seed / "main.tex").write_text("reset history\n")
    git(seed, "add", "main.tex")
    git(seed, "commit", "-q", "-m", "reset")
    git(seed, "push", "-q", "-f", "origin", "HEAD:master")
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "base is not in Overleaf history" in result.output
    assert "Set base, in a PR" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert not git(project, "status", "--porcelain")


def test_bibliography_refuses_edit_deleted_on_overleaf(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/references.bib").write_text("@misc{workspace_edit}\n")
    commit_all(project)
    before = (project / ".asta/overleaf/paper.json").read_bytes()
    overleaf_edit(seed, "references.bib", None)
    result = run(project, "pull")
    assert result.exit_code != 0
    assert "disagree on whether references.bib exists" in result.output
    assert (project / "paper/references.bib").read_text() == "@misc{workspace_edit}\n"
    assert (project / ".asta/overleaf/paper.json").read_bytes() == before


def test_pull_imports_collaborator_bibliography_updates(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    overleaf_edit(seed, "references.bib", "@misc{collaborator}\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper/references.bib").read_text() == "@misc{collaborator}\n"
    assert (project / "references.bib").read_text() == "@misc{root}\n"


@pytest.mark.parametrize("directory", ["paper[1]", "paper*"])
def test_sync_uses_literal_paper_directory(setup, directory):
    seed, project = setup
    (project / "paper1").mkdir()
    (project / "paper1/main.tex").write_text("unrelated paper\n")
    commit_all(project)
    assert run(project, "pull", URL, "--dir", directory).exit_code == 0
    commit_all(project)
    source = project / directory / "main.tex"
    source.write_text("uncommitted edit\n")
    result = run(project, "publish", "--dir", directory)
    assert result.exit_code != 0 and "local changes" in result.output
    commit_all(project)
    result = run(project, "publish", "--dir", directory)
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_bytes() == source.read_bytes()
    assert (project / "paper1/main.tex").read_text() == "unrelated paper\n"


def test_publish_uses_repo_local_identity(setup, monkeypatch):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    for role in ("AUTHOR", "COMMITTER"):
        for field in ("NAME", "EMAIL"):
            monkeypatch.delenv(f"GIT_{role}_{field}")
    git(project, "config", "user.name", "Workspace Author")
    git(project, "config", "user.email", "workspace@example.invalid")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert git(seed, "log", "-1", "--format=%an <%ae>") == (
        "Workspace Author <workspace@example.invalid>"
    )


@pytest.mark.parametrize("name", [".gitignore", "nested/.gitignore"])
def test_publish_refuses_paper_ignore_rules_before_pushing(setup, name):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    path = project / "paper" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("*.aux\n")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    record = (project / ".asta/overleaf/paper.json").read_bytes()
    result = run(project, "publish")
    assert result.exit_code != 0 and ".gitignore" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / ".asta/overleaf/paper.json").read_bytes() == record


def test_publish_then_pull_with_workspace_ignore_rules(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / ".gitignore").write_text("*.aux\n")
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    assert not git(project, "status", "--porcelain")
    overleaf_edit(seed, "main.tex", "collaborator follow-up\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper/main.tex").read_text() == "collaborator follow-up\n"


def test_pull_refuses_overleaf_file_replacing_workspace_directory(setup):
    seed, project = setup
    (seed / "nested").mkdir()
    overleaf_edit(seed, "nested/figure.tex", "figure\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    record = _record(paper).read_bytes()
    git(seed, "rm", "-r", "-q", "nested")
    (seed / "nested").write_text("now a file\n")
    commit_all(seed)
    git(seed, "push", "-q", "origin", "master")
    result = run(project, "pull")
    assert result.exit_code != 0 and "Move the directory aside" in result.output
    assert (paper / "nested/figure.tex").read_text() == "figure\n"
    assert _record(paper).read_bytes() == record


def test_pull_empty_remote_commit(setup):
    seed, project = setup
    git(seed, "rm", "-r", ".")
    commit_all(seed)
    git(seed, "push", "-q", "origin", "master")
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    assert json.loads((project / ".asta/overleaf/paper.json").read_text())[
        "base"
    ] == git(seed, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "text",
    ["{", "[]", "null", '"value"', "{}", '{"url": 42, "base": "' + "a" * 40 + '"}'],
)
@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_reports_invalid_metadata(setup, text, command, monkeypatch):
    _, project = setup
    paper = project / "paper"
    paper.mkdir()
    _record(paper).write_text(text)
    commit_all(project)
    monkeypatch.setattr(module, "clone", lambda *a: pytest.fail("must not clone"))
    result = run(project, command)
    assert result.exit_code == 1
    assert (
        "Invalid sync record" in result.output
        and ".asta/overleaf/paper.json" in result.output
    )
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("operation", ["clone", "push"])
def test_git_rejection_names_the_operation(setup, monkeypatch, operation):
    _, project = setup
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(a[0], 1, b"", b"rejected")
        ),
    )
    with pytest.raises(module.click.ClickException) as error:
        module.git_bytes(operation, cwd=project)
    assert operation in str(error.value)
    assert "changed during publish" not in str(error.value)


def test_publish_refuses_ignored_untracked_sync_record(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "rm", "--cached", ".asta/overleaf/paper.json")
    (project / ".gitignore").write_text(".asta/overleaf/paper.json\n")
    commit_all(project)
    overleaf_edit(seed, "main.tex", "newer Overleaf content\n")
    path = project / ".asta/overleaf/paper.json"
    record = json.loads(path.read_text())
    record["base"] = git(seed, "rev-parse", "HEAD")
    path.write_text(json.dumps(record))
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code != 0 and "paper.json is ignored" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (seed / "main.tex").read_text() == "newer Overleaf content\n"
    assert json.loads(path.read_text()) == record


@pytest.mark.parametrize("pattern", ["*.png", "*.tex"])
def test_publish_preserves_sources_matching_global_ignore_rules(
    setup, monkeypatch, pattern
):
    seed, project = setup
    overleaf_edit(seed, "figure.png", "figure content\n")
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    ignore = project.parent / "global-ignore"
    ignore.write_text(pattern + "\n")
    config = project.parent / "global-config"
    config.write_text(f"[core]\nexcludesFile = {ignore}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "reviewed edit\n"
    assert (seed / "figure.png").read_text() == "figure content\n"


@pytest.mark.parametrize("operation", ["ls-tree", "cat-file", "rev-parse", "commit"])
@pytest.mark.parametrize("diagnostic", [b"path401", b"path403", b"rejected"])
def test_local_git_failures_do_not_report_overleaf_auth(
    setup, monkeypatch, operation, diagnostic
):
    _, project = setup
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(a[0], 1, b"", diagnostic)
        ),
    )
    with pytest.raises(module.click.ClickException) as error:
        module.git_bytes(operation, cwd=project)
    assert str(error.value).startswith(f"git {operation} failed (exit 1).")
    assert "Overleaf" not in str(error.value)


def test_pull_preserves_ignored_file_after_workspace_untracks_it(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "rm", "--cached", "paper/old.tex")
    (project / ".gitignore").write_text("paper/old.tex\n")
    commit_all(project)
    (project / "paper/old.tex").write_text("local ignored notes\n")
    overleaf_edit(seed, "old.tex", None)
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper/old.tex").read_text() == "local ignored notes\n"


@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_requires_configured_identity(setup, monkeypatch, dry_run):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    for role in ("AUTHOR", "COMMITTER"):
        for field in ("NAME", "EMAIL"):
            monkeypatch.delenv(f"GIT_{role}_{field}")
    before = git(seed, "ls-remote", "origin", "master")
    record = (project / ".asta/overleaf/paper.json").read_bytes()
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert (
        result.exit_code != 0
        and "Configure Git user.name and user.email" in result.output
    )
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / ".asta/overleaf/paper.json").read_bytes() == record


def test_pull_reports_unavailable_base_before_modifying_sources(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    path = project / ".asta/overleaf/paper.json"
    config = json.loads(path.read_text())
    config["base"] = "0" * 40
    path.write_text(json.dumps(config))
    commit_all(project)
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    result = run(project, "pull")
    assert result.exit_code == 1, result.output
    assert "base is not in Overleaf history" in result.output
    assert (
        "Set base, in a PR, to an Overleaf commit the default branch already has"
        in result.output
    )
    assert module.RECOVERY in result.output
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_reports_unavailable_recorded_base_without_pushing(setup, dry_run):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    paper = project / "paper"
    record = project / ".asta/overleaf/paper.json"
    config = json.loads(record.read_text())
    config["base"] = "0" * 40
    record.write_text(json.dumps(config))
    commit_all(project)
    before = {p.name: p.read_bytes() for p in paper.iterdir()}
    before_remote = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert result.exit_code == 1, result.output
    assert "base is not in Overleaf history" in result.output
    assert (
        "Set base, in a PR, to an Overleaf commit the default branch already has"
        in result.output
    )
    assert "nothing pushed" in result.output
    assert module.RECOVERY in result.output
    assert {p.name: p.read_bytes() for p in paper.iterdir()} == before
    assert git(seed, "ls-remote", "origin", "master") == before_remote
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("diverge", [False, True])
def test_pull_refuses_reset_history_with_base_on_another_branch(setup, diverge):
    seed, project = setup
    overleaf_edit(seed, "main.tex", "before reset\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    before = {p.name: p.read_bytes() for p in paper.iterdir()}
    git(seed, "branch", "preserved-base")
    git(seed, "push", "origin", "preserved-base")
    git(seed, "reset", "--hard", "HEAD~1")
    if diverge:
        (seed / "main.tex").write_text("different history\n")
        git(seed, "add", "main.tex")
        git(seed, "commit", "-m", "diverge")
    git(seed, "push", "--force", "origin", "master")

    result = run(project, "pull")

    assert result.exit_code != 0
    assert "base is not in Overleaf history" in result.output
    assert "Set base, in a PR" in result.output
    assert {p.name: p.read_bytes() for p in paper.iterdir()} == before
    assert git(project, "status", "--porcelain") == ""


def test_project_subdirectory_keeps_paper_relative_to_repository(setup):
    _, project = setup
    nested = project / "notes"
    nested.mkdir()
    result = CliRunner().invoke(
        cli, ["workspace", "overleaf", "pull", URL, "--project", str(nested)]
    )
    assert result.exit_code == 0, result.output
    assert (project / "paper/main.tex").exists()
    assert not (nested / "paper").exists()


def test_publish_refuses_record_hidden_by_index_flags(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    overleaf_edit(seed, "main.tex", "new remote revision\n")
    git(project, "update-index", "--assume-unchanged", ".asta/overleaf/paper.json")
    record = project / ".asta/overleaf/paper.json"
    config = json.loads(record.read_text())
    config["base"] = git(seed, "rev-parse", "HEAD")
    record.write_text(json.dumps(config))
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert (
        result.exit_code != 0 and "differs from the committed revision" in result.output
    )
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
@pytest.mark.parametrize("local_edit", ["uncommitted local edits\n", None])
@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_refuses_source_changes_hidden_by_index_flags(
    setup, monkeypatch, flag, local_edit, dry_run
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    source = project / "paper/main.tex"
    git(project, "update-index", flag, "paper/main.tex")
    if local_edit is None:
        source.unlink()
    else:
        source.write_text(local_edit)
    assert git(project, "status", "--porcelain") == ""
    record = (project / ".asta/overleaf/paper.json").read_bytes()
    before = git(seed, "ls-remote", "origin", "master")
    monkeypatch.setattr(
        module, "clone", lambda *args: pytest.fail("must refuse before transport")
    )
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert result.exit_code != 0 and "local changes" in result.output
    assert "paper/main.tex" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / ".asta/overleaf/paper.json").read_bytes() == record
    if local_edit is None:
        assert not source.exists()
    else:
        assert source.read_text() == local_edit


@pytest.mark.parametrize("command", ["pull", "publish"])
@pytest.mark.parametrize(
    "name",
    [".GITATTRIBUTES", "nested/.gitattributeſ", ".GitIgnore", "nested/.GITIGNORE"],
)
def test_sync_refuses_reserved_filename_aliases(setup, command, name):
    seed, project = setup
    if command == "publish":
        assert run(project, "pull", URL).exit_code == 0
        commit_all(project)
    target = (seed if command == "pull" else project / "paper") / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("*\n")
    if command == "pull":
        git(seed, "add", name)
        git(seed, "commit", "-m", "reserved filename")
        git(seed, "push", "origin", "master")
    else:
        commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, command, *([URL] if command == "pull" else []))
    assert result.exit_code != 0
    expected = (
        "ignore rules can hide imported sources"
        if "ignore" in name.casefold()
        else "copies plain files only"
    )
    assert expected in result.output
    assert name in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    if command == "pull":
        assert not (project / "paper").exists()


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
@pytest.mark.parametrize("remote_edit", ["updated remote source\n", None])
def test_pull_preserves_local_edits_hidden_by_index_flags(setup, flag, remote_edit):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    source = project / "paper/main.tex"
    git(project, "update-index", flag, "paper/main.tex")
    source.write_text("uncommitted local edits\n")
    assert git(project, "status", "--porcelain") == ""
    record = (project / ".asta/overleaf/paper.json").read_bytes()
    overleaf_edit(seed, "main.tex", remote_edit)
    result = run(project, "pull")
    assert result.exit_code != 0 and "local changes" in result.output
    assert source.read_text() == "uncommitted local edits\n"
    assert (project / ".asta/overleaf/paper.json").read_bytes() == record
    assert (project / "paper/old.tex").read_text() == "old\n"


def test_pull_preserves_sync_record_hidden_by_index_flags(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "update-index", "--assume-unchanged", ".asta/overleaf/paper.json")
    record = project / ".asta/overleaf/paper.json"
    record.write_bytes(record.read_bytes() + b" \n")
    before = record.read_bytes()
    overleaf_edit(seed, "main.tex", "remote update\n")
    result = run(project, "pull")
    assert result.exit_code != 0 and "local changes" in result.output
    assert record.read_bytes() == before
    assert (project / "paper/main.tex").read_text() == "hello\n"


def test_pull_allows_unrelated_update_after_workspace_deletes_and_ignores_file(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "rm", "paper/old.tex")
    (project / ".gitignore").write_text("paper/old.tex\n")
    commit_all(project)
    overleaf_edit(seed, "main.tex", "unrelated Overleaf update\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert not (project / "paper/old.tex").exists()
    assert (project / "paper/main.tex").read_text() == "unrelated Overleaf update\n"
    assert json.loads((project / ".asta/overleaf/paper.json").read_text())[
        "base"
    ] == git(seed, "rev-parse", "HEAD")


def test_pull_preserves_hidden_local_edit_when_overleaf_did_not_change_file(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "update-index", "--assume-unchanged", "paper/old.tex")
    local = project / "paper/old.tex"
    local.write_text("hidden local notes\n")
    overleaf_edit(seed, "main.tex", "unrelated update\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert local.read_text() == "hidden local notes\n"
    assert (project / "paper/main.tex").read_text() == "unrelated update\n"


@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_refuses_empty_export_without_changing_remote(setup, dry_run):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    for name in ("main.tex", "old.tex", "references.bib"):
        git(project, "rm", f"paper/{name}")
    commit_all(project)
    before = (project / ".asta/overleaf/paper.json").read_bytes()
    remote_before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert result.exit_code != 0 and "empty paper" in result.output
    assert (project / ".asta/overleaf/paper.json").read_bytes() == before
    assert git(seed, "ls-remote", "origin", "master") == remote_before


@pytest.mark.skipif(os.name == "nt", reason="POSIX askpass")
def test_token_credentials_supply_fixed_username_without_prompt(setup, monkeypatch):
    _, project = setup
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    with module.credentials() as (env, options):
        result = subprocess.run(
            ["git", *options, "credential", "fill"],
            cwd=project,
            env=env,
            input=b"url=https://git@git.overleaf.com/1234567\n\n",
            check=True,
            capture_output=True,
        )
    assert b"username=git\n" in result.stdout
    assert b"password=fixture-token\n" in result.stdout


@pytest.mark.parametrize(
    "operation,message", [("clone", "failed"), ("push", "was rejected")]
)
def test_git_rejection_classification_applies_only_to_push(
    tmp_path, monkeypatch, operation, message
):
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(
                a[0], 128, b"", b"request rejected"
            )
        ),
    )
    with pytest.raises(module.click.ClickException, match=f"git {operation} {message}"):
        module.git_bytes(operation, cwd=tmp_path)


def test_git_environment_preserves_all_locale_settings(monkeypatch):
    for key, value in (
        ("LC_ALL", "C.UTF-8"),
        ("LC_MESSAGES", "C.UTF-8"),
        ("LANGUAGE", "fixture-language"),
    ):
        monkeypatch.setenv(key, value)
        assert module.git_environment()[key] == value


def test_clone_supplies_git_username_in_transport_url(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        module, "git", lambda *args, **kwargs: calls.append(args) or "a" * 40
    )
    module.clone(URL, tmp_path / "overleaf")
    assert URL.replace("https://", "https://git@", 1) in calls[0]
    assert URL not in calls[0]


LATEX_OUTPUTS = (
    "main.aux",
    "main.log",
    "main.bbl",
    "main.blg",
    "main.fls",
    "main.fdb_latexmk",
    "main.synctex.gz",
    "main.out",
    "main.pdf",
)


def compile_locally(paper):
    for name in LATEX_OUTPUTS:
        (paper / name).write_text("build output\n")


def test_local_latex_build_does_not_block_pull_or_publish(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    compile_locally(paper)
    overleaf_edit(seed, "main.tex", "collaborator\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (paper / "main.tex").read_text() == "collaborator\n"
    git(project, "add", "--", "paper/main.tex", ".asta/overleaf/paper.json")
    git(project, "commit", "-q", "-m", "sync")
    (paper / "main.tex").write_text("reviewed\n")
    git(project, "add", "--", "paper/main.tex")
    git(project, "commit", "-q", "-m", "edit")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "reviewed\n"
    for name in LATEX_OUTPUTS:
        assert not (seed / name).exists()
        assert (paper / name).read_text() == "build output\n"


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_untracked_non_build_files_still_block_sync(setup, command):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    paper = project / "paper"
    compile_locally(paper)
    # A PDF without a matching .tex is a source (e.g. a figure), not a build output.
    (paper / "figure.pdf").write_text("figure\n")
    result = run(project, command)
    assert result.exit_code != 0
    assert "local changes" in result.output


def test_modified_tracked_build_output_still_blocks_sync(setup):
    seed, project = setup
    overleaf_edit(seed, "main.bbl", "committed bbl\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper" / "main.bbl").write_text("rebuilt\n")
    result = run(project, "pull")
    assert result.exit_code != 0
    assert "local changes" in result.output


def test_publish_pdf_asset_requires_commit_even_with_matching_tex(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    paper = project / "paper"
    (paper / "figure.tex").write_text("figure source\n")
    commit_all(project)
    asset = paper / "figure.pdf"
    asset.write_bytes(b"paper figure asset\n")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert not (seed / "figure.pdf").exists()
    assert asset.read_bytes() == b"paper figure asset\n"
    git(project, "add", "--", "paper/figure.pdf", ".asta/overleaf/paper.json")
    git(project, "commit", "-q", "-m", "include reviewed figure")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "figure.pdf").read_bytes() == asset.read_bytes()
    assert not git(project, "status", "--porcelain")
    before_record = _record(paper).read_bytes()
    before_remote = git(seed, "rev-parse", "HEAD")
    asset.write_bytes(b"unreviewed figure change\n")
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "local changes" in result.output
    assert git(seed, "ls-remote", "origin", "master").split()[0] == before_remote
    assert _record(paper).read_bytes() == before_record
    assert (seed / "figure.pdf").read_bytes() == b"paper figure asset\n"


@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_requires_revision_on_origin_default_branch(setup, dry_run):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "push", "-q", "origin", "main")
    git(project, "switch", "-q", "-c", "feature")
    (project / "paper" / "main.tex").write_text("unreviewed\n")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    args = ["publish", "--dry-run"] if dry_run else ["publish"]
    result = run(project, *args, merge=False)
    assert git(seed, "ls-remote", "origin", "master") == before
    assert "differs from the latest commit on origin's default branch" in result.output
    if dry_run:
        assert result.exit_code == 0, result.output
        assert "main.tex" in result.output
    else:
        assert result.exit_code != 0
        assert "nothing pushed" in result.output
    git(project, "switch", "-q", "main")
    git(project, "merge", "-q", "feature")
    git(project, "push", "-q", "origin", "main")
    result = run(project, "publish", merge=False)
    assert result.exit_code == 0, result.output
    assert git(seed, "ls-remote", "origin", "master") != before


def test_publish_requires_origin_remote(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "remote", "remove", "origin")
    (project / "paper" / "main.tex").write_text("edit\n")
    commit_all(project)
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish", merge=False)
    assert result.exit_code != 0
    assert "`origin` remote" in result.output
    assert "nothing pushed" in result.output.lower()
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize("merged", [False, True])
def test_merge_gate_preserves_previous_fetch_and_workspace_refs(setup, merged):
    _, project = setup
    git(project, "fetch", "-q", "origin", "main")
    fetch_head = project / git(project, "rev-parse", "--git-path", "FETCH_HEAD")
    before_fetch = fetch_head.read_bytes()
    (project / "reviewed.txt").write_text("reviewed revision\n")
    commit_all(project)
    if merged:
        git(project, "push", "-q", "origin", "HEAD:main")
    before_refs = git(project, "show-ref")
    with module.default_branch(project) as (tip, _):
        assert (module.tree(project, tip) == module.tree(project, "HEAD")) == merged
    assert fetch_head.read_bytes() == before_fetch
    assert git(project, "show-ref") == before_refs


def test_merge_gate_accepts_older_checkout_with_current_paper(setup):
    _, project = setup
    (project / "paper").mkdir()
    (project / "paper" / "main.tex").write_text("reviewed paper\n")
    commit_all(project)
    reviewed = git(project, "rev-parse", "HEAD")
    (project / "later.txt").write_text("later merged revision outside the paper\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    git(project, "switch", "-q", "--detach", reviewed)
    with module.default_branch(project) as (tip, _):
        assert module.tree(project, tip, "paper/") == module.tree(
            project, "HEAD", "paper/"
        )


@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_refuses_older_checkout_after_later_paper_change(setup, dry_run):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper" / "retracted.tex").write_text("later removed\n")
    commit_all(project)
    reviewed = git(project, "rev-parse", "HEAD")
    git(project, "rm", "-q", "paper/retracted.tex")
    git(project, "commit", "-q", "-m", "remove section in review")
    git(project, "push", "-q", "origin", "HEAD:main")
    git(project, "switch", "-q", "--detach", reviewed)
    before = git(seed, "ls-remote", "origin", "master")
    args = ["publish", "--dry-run"] if dry_run else ["publish"]
    result = run(project, *args, merge=False)
    assert "differs from the latest commit" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    if dry_run:
        assert result.exit_code == 0, result.output
    else:
        assert result.exit_code != 0
        assert "nothing pushed" in result.output


@pytest.mark.parametrize("name", ["experiment.log", "submission.bbl"])
def test_untracked_build_suffix_assets_require_commit_for_export(setup, name):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    asset = project / "paper" / name
    asset.write_bytes(b"paper asset\n")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert asset.read_bytes() == b"paper asset\n"
    assert not (seed / name).exists()
    git(project, "add", "--", ".asta/overleaf/paper.json", f"paper/{name}")
    git(project, "commit", "-q", "-m", "review asset")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / name).read_bytes() == b"paper asset\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX commit hook")
def test_workspace_only_hook_config_failure_explains_export_layout(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    (project / ".pre-commit-config.yaml").write_text("repos: []\n")
    commit_all(project)
    before_record = (project / ".asta/overleaf/paper.json").read_bytes()
    before_remote = git(seed, "ls-remote", "origin", "master")
    hook = project / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\ntest -f .pre-commit-config.yaml\n")
    hook.chmod(0o700)
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "commit hooks and signing settings" in result.output
    assert "exported paper directory, not the full workspace" in result.output
    assert (project / ".asta/overleaf/paper.json").read_bytes() == before_record
    assert git(seed, "ls-remote", "origin", "master") == before_remote


@pytest.mark.parametrize("interactive", [False, True])
def test_merge_gate_workspace_transport_respects_terminal(
    setup, monkeypatch, interactive
):
    _, project = setup
    monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
    monkeypatch.setattr(
        module,
        "sys",
        SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: interactive)),
    )
    real = module.subprocess.run
    observed = []

    def inspect_transport(args, **kwargs):
        if args[1] in ("ls-remote", "fetch"):
            observed.append((args[1], kwargs["env"].get("GIT_TERMINAL_PROMPT")))
        return real(args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", inspect_transport)
    with module.default_branch(project) as (tip, _):
        assert module.tree(project, tip) == module.tree(project, "HEAD")
    assert observed == [
        ("ls-remote", None if interactive else "0"),
        ("fetch", None if interactive else "0"),
    ]


def test_workspace_missing_credentials_fail_without_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    monkeypatch.delenv("GIT_ASKPASS", raising=False)
    monkeypatch.delenv("SSH_ASKPASS", raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setattr(
        module, "sys", SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: False))
    )
    result = subprocess.run(
        ["git", "-c", "credential.helper=", "credential", "fill"],
        cwd=tmp_path,
        env=module.git_environment(),
        input=b"url=https://example.com/workspace.git\n\n",
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert b"terminal prompts disabled" in result.stderr


@pytest.mark.parametrize(
    "name",
    ["fig.tikz", "fig.pgf", "data.csv", "data.tsv", "data.dat", "a.bbx", "a.cbx"],
)
def test_figure_and_data_sources_merge_line_by_line(setup, name):
    seed, project = setup
    overleaf_edit(seed, name, "one\ntwo\nthree\nfour\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper" / name).write_text("ONE\ntwo\nthree\nfour\n")
    commit_all(project)
    overleaf_edit(seed, name, "one\ntwo\nthree\nFOUR\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper" / name).read_text() == "ONE\ntwo\nthree\nFOUR\n"


def test_publish_reports_overleaf_race(setup, monkeypatch):
    _, project = setup
    stderr = b" ! [rejected] HEAD -> master (fetch first)"
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(a[0], 1, b"", stderr)
        ),
    )
    with pytest.raises(module.click.ClickException) as error:
        module.git_bytes("push", cwd=project)
    assert "Overleaf changed while publishing" in str(error.value)
    assert "overleaf pull" in str(error.value)


@pytest.mark.parametrize("diagnostic", ["non-fast-forward", "fetch first"])
def test_push_hook_text_is_not_classified_as_overleaf_race(
    tmp_path, monkeypatch, diagnostic
):
    stderr = f"remote: policy mentions {diagnostic}\n ! [remote rejected] HEAD -> master (policy refused)".encode()
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(a[0], 1, b"", stderr)
        ),
    )
    with pytest.raises(module.click.ClickException) as error:
        module.git_bytes("push", cwd=tmp_path)
    assert "was rejected" in str(error.value)
    assert "Overleaf changed" not in str(error.value)


@pytest.mark.parametrize(
    "url", [URL + "/", URL + ".git", URL.replace("https://", "https://git@")]
)
@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("url_location", ["caller", "record"])
def test_pull_recognizes_publications_with_equivalent_url(setup, url, url_location):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("published paper\n")
    if url_location == "record":
        record = project / ".asta/overleaf/paper.json"
        record.write_text(record.read_text().replace(URL, url))
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    result = run(project, "pull", url if url_location == "caller" else URL)
    assert result.exit_code == 0, result.output
    assert (project / "paper/main.tex").read_text() == "collaborator edit\n"
    assert "recorded sync" not in result.output


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_expected_publish_accepts_uppercase_commit_id(setup):
    seed, project, expected = prepare_expected_publication(setup)
    result = run(project, "publish", "--expected-commit", expected.upper(), merge=False)
    assert result.exit_code == 0, result.output
    git(seed, "pull", "--ff-only")
    assert (
        git(seed, "log", "-1", "--format=%s") == f"Publish workspace commit {expected}"
    )


@pytest.mark.parametrize("command", ["pull", "publish", "dry-run"])
def test_gate_cleanup_failure_does_not_hide_original_error(setup, monkeypatch, command):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    real = module.subprocess.run

    def fail_git(args, **kwargs):
        if "update-ref" in args and "-d" in args:
            return subprocess.CompletedProcess(
                args, 128, b"", b"fixture-secret cleanup"
            )
        if ("ls-remote" in args and "--symref" in args) or (
            "fetch" in args and any("refs/asta/overleaf/" in a for a in args)
        ):
            return subprocess.CompletedProcess(args, 128, b"", b"fixture-secret origin")
        return real(args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", fail_git)
    result = (
        run(project, "publish", "--dry-run", merge=False)
        if command == "dry-run"
        else run(project, command, merge=False)
    )
    assert result.exit_code == 1
    assert (
        "Could not fetch" in result.output
        or "Could not read the Overleaf sync record" in result.output
    )
    assert "git update-ref failed" not in result.output
    assert "fixture-secret" not in result.output


@pytest.mark.parametrize("dry_run", [False, True])
def test_reset_history_publish_uses_one_nothing_pushed_suffix(setup, dry_run):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(seed, "switch", "--orphan", "reset")
    (seed / "main.tex").write_text("reset\n")
    commit_all(seed)
    git(seed, "push", "--force", "origin", "HEAD:master")
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert result.exit_code == 1, result.output
    assert "base is not in Overleaf history" in result.output
    assert "nothing synced" not in result.output
    assert result.output.lower().count("nothing pushed") == 1


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_pull_allows_directory_named_overleaf_json_after_publication(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("published\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    git(seed, "pull", "--ff-only")
    (seed / "overleaf.json").mkdir()
    overleaf_edit(seed, "overleaf.json/child.tex", "paper source\n")

    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper/overleaf.json/child.tex").read_text() == "paper source\n"


RECORD_REF = "refs/asta/overleaf/1234567"


def forge_record(origin, data, parent=None):
    """Build an arbitrary record object without changing the published ref."""
    payload = data if isinstance(data, str) else json.dumps(data)
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=origin,
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "mktree"],
        cwd=origin,
        input=f"100644 blob {blob}\tsync.json\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return git(
        origin, "commit-tree", tree, *(["-p", parent] if parent else []), "-m", "record"
    )


def origin_record(tmp_path):
    origin = tmp_path / "workspace.git"
    commit = git(origin, "rev-parse", "--verify", "-q", RECORD_REF)
    return commit, json.loads(git(origin, "show", f"{commit}:sync.json"))


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_publish_records_sync_point_on_workspace_origin(setup, tmp_path):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    record = (project / ".asta/overleaf/paper.json").read_bytes()
    for text in ("first publication\n", "second publication\n"):
        (project / "paper/main.tex").write_text(text)
        commit_all(project)
        result = run(project, "publish")
        assert result.exit_code == 0, result.output
        assert (project / ".asta/overleaf/paper.json").read_bytes() == record
        assert not git(project, "status", "--porcelain")
        commit, data = origin_record(tmp_path)
        assert data == {
            "format": module.FORMAT,
            "requires_asta": module.FORMAT_RELEASE,
            "url": URL,
            "overleaf": git(seed, "ls-remote", "origin", "master").split()[0],
            "workspace": git(project, "rev-parse", "HEAD"),
        }
        if text.startswith("first"):
            first = commit
        else:
            assert git(tmp_path / "workspace.git", "rev-parse", f"{commit}^") == first
    assert not git(project, "for-each-ref", "refs/asta")
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert (project / "paper/main.tex").read_text() == "collaborator edit\n"


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_publish_keeps_previous_record_reachable_until_push(
    setup, tmp_path, monkeypatch
):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("first publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    previous, _ = origin_record(tmp_path)
    (project / "paper/main.tex").write_text("second publication\n")
    commit_all(project)
    real = module.record_publication

    def prune_before_record(*args, **kwargs):
        git(project, "prune", "--expire=now")
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "record_publication", prune_before_record)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    current, _ = origin_record(tmp_path)
    assert git(tmp_path / "workspace.git", "rev-parse", f"{current}^") == previous
    assert not git(project, "for-each-ref", "refs/asta")
    assert not git(project, "status", "--porcelain")


def test_forged_publication_subject_does_not_move_sync_point(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text("reviewed\n")
    commit_all(project)
    reviewed = git(project, "rev-parse", "HEAD")
    git(project, "push", "-q", "origin", "HEAD:main")
    git(seed, "pull", "-q", "origin", "master")
    (seed / "main.tex").write_text("reviewed\n")
    git(seed, "commit", "-qam", f"Publish workspace commit {reviewed}")
    git(seed, "push", "-q", "origin", "master")
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code == 1 and "Overleaf has changed" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX hook")
def test_publish_records_commit_translated_by_git_integration(setup, tmp_path):
    seed, project = setup
    hook = tmp_path / "overleaf.git" / "hooks" / "post-receive"
    hook.write_text(
        "#!/bin/sh\n"
        "head=$(git rev-parse refs/heads/master)\n"
        'tree=$(git rev-parse "$head^{tree}")\n'
        'parent=$(git rev-parse "$head^")\n'
        'new=$(echo translated | git commit-tree "$tree" -p "$parent")\n'
        'git update-ref refs/heads/master "$new"\n'
    )
    hook.chmod(0o755)
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    for text in ("first\n", "second\n"):
        (project / "paper/main.tex").write_text(text)
        commit_all(project)
        result = run(project, "publish")
        assert result.exit_code == 0, result.output
        translated = git(seed, "ls-remote", "origin", "master").split()[0]
        assert origin_record(tmp_path)[1]["overleaf"] == translated


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("already_published", [False, True])
def test_publish_records_its_commit_before_a_concurrent_overleaf_edit(
    setup, tmp_path, monkeypatch, already_published
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    if already_published:
        (project / "paper/main.tex").write_text("first publication\n")
        commit_all(project)
        assert run(project, "publish").exit_code == 0
    before_config = (project / ".asta/overleaf/paper.json").read_bytes()
    (project / "paper/main.tex").write_text("published paper\n")
    commit_all(project)
    expected = git(project, "rev-parse", "HEAD")
    pushed = None
    real_push = module.push

    def push_then_edit(repo, root, **kwargs):
        nonlocal pushed
        real_push(repo, root, **kwargs)
        pushed = git(repo, "rev-parse", "HEAD")
        overleaf_edit(seed, "main.tex", "collaborator edit after publication\n")

    with monkeypatch.context() as patch:
        patch.setattr(module, "push", push_then_edit)
        result = run(project, "publish", "--expected-commit", expected)
    assert result.exit_code == 0, result.output
    _, record = origin_record(tmp_path)
    remote_head = git(seed, "rev-parse", "HEAD")
    assert record == {
        "format": module.FORMAT,
        "requires_asta": module.FORMAT_RELEASE,
        "url": URL,
        "overleaf": pushed,
        "workspace": expected,
    }
    assert remote_head != pushed
    assert git(seed, "rev-parse", f"{remote_head}^") == pushed
    assert (project / ".asta/overleaf/paper.json").read_bytes() == before_config
    assert not git(project, "status", "--porcelain")
    assert not git(project, "for-each-ref", "refs/asta")

    # Recording the collaborator's head would hide their edit from pull.
    refused = run(project, "publish", merge=False)
    assert refused.exit_code == 1 and "Overleaf has changed" in refused.output
    assert git(seed, "ls-remote", "origin", "master").split()[0] == remote_head
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert (project / "paper/main.tex").read_text() == (
        "collaborator edit after publication\n"
    )
    assert json.loads((project / ".asta/overleaf/paper.json").read_text())["base"] == (
        remote_head
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX hook")
@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize(
    ("already_published", "parent"),
    [(False, "none"), (True, "none"), (True, "base")],
)
def test_publish_does_not_record_same_tree_history_reset(
    setup, tmp_path, already_published, parent
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    config = (project / ".asta/overleaf/paper.json").read_bytes()
    base = json.loads(config)["base"]
    if already_published:
        (project / "paper/main.tex").write_text("first publication\n")
        commit_all(project)
        assert run(project, "publish").exit_code == 0
    origin = tmp_path / "workspace.git"
    before_record = git(origin, "for-each-ref", RECORD_REF)
    hook = tmp_path / "overleaf.git" / "hooks" / "post-receive"
    parent_option = f" -p {base}" if parent == "base" else ""
    hook.write_text(
        "#!/bin/sh\n"
        "head=$(git rev-parse refs/heads/master)\n"
        'tree=$(git rev-parse "$head^{tree}")\n'
        f'new=$(echo reset | git commit-tree "$tree"{parent_option})\n'
        'git update-ref refs/heads/master "$new"\n'
    )
    hook.chmod(0o755)
    (project / "paper/main.tex").write_text("second publication\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 1, result.output
    assert "could not confirm Overleaf's copy" in result.output
    assert (
        "merge the resulting PR (it may change only the paper's .asta/overleaf record)"
        in result.output
    )
    assert git(origin, "for-each-ref", RECORD_REF) == before_record
    assert (project / ".asta/overleaf/paper.json").read_bytes() == config
    assert not git(project, "status", "--porcelain")
    # The Overleaf push succeeded; only confirmation and recording are refused.
    git(seed, "fetch", "origin", "master")
    assert git(seed, "show", "FETCH_HEAD:main.tex") == "second publication"


@pytest.mark.skipif(os.name == "nt", reason="POSIX hook")
def test_record_push_failure_explains_recovery(setup, tmp_path):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    hook = tmp_path / "workspace.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\ngrep -q refs/asta/ && exit 1\nexit 0\n")
    hook.chmod(0o755)
    (project / "paper/main.tex").write_text("published\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 1
    assert "Published Overleaf commit" in result.output
    assert (
        "merge the resulting PR (it may change only the paper's .asta/overleaf record)"
        in result.output
    )
    hook.unlink()
    assert "Overleaf has changed" in run(project, "publish").output
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert git(project, "diff", "--name-only") == ".asta/overleaf/paper.json"
    commit_all(project)
    (project / "paper/main.tex").write_text("next\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX hook")
def test_record_push_skips_workspace_pre_push_hooks(setup, tmp_path):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    hook = project / ".git/hooks/pre-push"
    hook.write_text(
        "#!/bin/sh\n"
        "while read local_ref local_oid remote_ref remote_oid; do\n"
        '  case "$remote_ref" in refs/asta/overleaf/*) exit 1;; esac\n'
        "done\n"
    )
    hook.chmod(0o755)
    (project / "paper/main.tex").write_text("first publication\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert origin_record(tmp_path)[1]["workspace"] == git(project, "rev-parse", "HEAD")
    (project / "paper/main.tex").write_text("second publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0


def test_record_not_matching_reviewed_history_falls_back(setup, tmp_path):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("published\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    # An unreviewed Overleaf edit attested by a forged record is not trusted.
    git(seed, "fetch", "-q", "origin", "master")
    git(seed, "reset", "-q", "--hard", "FETCH_HEAD")
    (seed / "main.tex").write_text("unreviewed\n")
    git(seed, "commit", "-qam", "edit")
    git(seed, "push", "-q", "origin", "HEAD:master")
    origin = tmp_path / "workspace.git"
    _, record = origin_record(tmp_path)
    record["overleaf"] = git(seed, "rev-parse", "HEAD")
    forged = forge_record(origin, record)
    git(origin, "update-ref", RECORD_REF, forged)
    result = run(project, "publish")
    assert result.exit_code == 1
    assert "does not match a paper on origin's default branch" in result.output
    assert module.RECOVERY in result.output
    assert f"{module.RECOVERY}#overleaf-edits-need-review" in result.output
    pulled = run(project, "pull")
    # Falling back to the last pull brings the unreviewed edit in for review.
    assert pulled.exit_code == CONFLICT_EXIT, pulled.output
    assert "unreviewed" in (project / "paper/main.tex").read_text()


def test_pull_missing_origin_default_branch_refuses_before_copying(setup, tmp_path):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("published\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    git(tmp_path / "workspace.git", "symbolic-ref", "HEAD", "refs/heads/missing")
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    result = run(project, "pull")
    assert result.exit_code == 1, result.output
    assert "Could not fetch the default branch" in result.output
    assert "Nothing copied." in result.output
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before
    assert not git(project, "status", "--porcelain")
    assert not git(project, "for-each-ref", "refs/asta")


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("object_type", ["tree", "tag-tree", "tag-commit"])
@pytest.mark.parametrize("command", ["pull", "publish", "dry-run"])
def test_noncommit_sync_record(setup, tmp_path, object_type, command):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("first publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    origin = tmp_path / "workspace.git"
    commit, _ = origin_record(tmp_path)
    target = git(origin, "rev-parse", f"{commit}^{{tree}}")
    if object_type.startswith("tag-"):
        if object_type == "tag-commit":
            target = commit
        git(origin, "tag", "-a", "invalid-record", "-m", "tagged record", target)
        target = git(origin, "rev-parse", "refs/tags/invalid-record")
    git(origin, "update-ref", RECORD_REF, target)
    assert git(origin, "cat-file", "-t", target) != "commit"
    if command == "pull":
        overleaf_edit(seed, "main.tex", "collaborator edit\n")
    else:
        (project / "paper/main.tex").write_text("second publication\n")
        commit_all(project)
        git(project, "push", "origin", "main")
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    remote = git(seed, "ls-remote", "origin", "master")
    result = run(
        project,
        "publish" if command == "dry-run" else command,
        *(["--dry-run"] if command == "dry-run" else []),
        merge=False,
    )
    if command == "pull":
        # Pull trusts the committed base instead of refusing on a damaged record.
        # Starting from the older base can conflict; it must not lose the edit.
        assert "Overleaf sync record not used: it is damaged" in result.output
        assert "Copied Overleaf commit" in result.output
        assert "collaborator edit" in (project / "paper/main.tex").read_text()
    else:
        assert result.exit_code == 1, result.output
        assert "Invalid Overleaf sync record" in result.output
        assert "Nothing pushed" in result.output
        assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before
        assert git(seed, "ls-remote", "origin", "master") == remote
    assert git(origin, "rev-parse", RECORD_REF) == target
    assert not git(project, "for-each-ref", "refs/asta")
    if command != "pull":
        assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_damaged_sync_record_starts_from_base(setup, tmp_path, command):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    origin = tmp_path / "workspace.git"
    forged = forge_record(
        origin, {"url": "https://git.overleaf.com/other", "overleaf": "0" * 40}
    )
    git(origin, "update-ref", RECORD_REF, forged)
    (project / "paper/main.tex").write_text("edit\n")
    commit_all(project)
    result = run(project, command)
    assert result.exit_code == 0, result.output
    assert "Overleaf sync record not used: it is damaged" in result.output


def test_pull_without_origin_uses_committed_record(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "remote", "remove", "origin")
    overleaf_edit(seed, "main.tex", "collaborator\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert "No `origin` remote" in result.output
    assert (project / "paper/main.tex").read_text() == "collaborator\n"


def unreviewed_record(project, origin, record):
    """Point the record at a workspace commit that is not on the default branch."""
    tree = git(project, "rev-parse", "HEAD^{tree}")
    stray = git(project, "commit-tree", tree, "-p", "HEAD", "-m", "unreviewed")
    git(
        origin,
        "update-ref",
        RECORD_REF,
        forge_record(origin, {**record, "workspace": stray}),
    )


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_record_written_by_publish_counts(setup, tmp_path):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text("publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    overleaf_edit(seed, "main.tex", "publication\ncollaborator\n")
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert "record not used" not in pulled.output
    assert (project / "paper/main.tex").read_text() == "publication\ncollaborator\n"


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_record_off_the_default_branch_starts_from_base(setup, tmp_path):
    seed, project = setup
    origin = tmp_path / "workspace.git"
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text("publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    unreviewed_record(project, origin, origin_record(tmp_path)[1])
    overleaf_edit(seed, "references.bib", "@misc{collaborator}\n")
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert "Overleaf sync record not used: it does not match" in pulled.output
    assert f"{module.RECOVERY}#record-not-used" in pulled.output
    # Starting from base re-applies the published edit, which the workspace has.
    assert (project / "paper/main.tex").read_text() == "publication\n"
    assert (project / "paper/references.bib").read_text() == "@misc{collaborator}\n"


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("damage", ["damaged", "unreviewed"])
def test_pull_from_base_after_publish_neither_repeats_nor_skips_edits(
    setup, tmp_path, damage
):
    seed, project = setup
    origin = tmp_path / "workspace.git"
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    overleaf_edit(seed, "references.bib", "@misc{before}\n")
    assert run(project, "pull").exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text("publication one\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    overleaf_edit(seed, "references.bib", "@misc{before}\n@misc{between}\n")
    assert run(project, "pull").exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text("publication two\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    if damage == "damaged":
        git(origin, "update-ref", RECORD_REF, forge_record(origin, "not json"))
    else:
        unreviewed_record(project, origin, origin_record(tmp_path)[1])
    overleaf_edit(
        seed, "references.bib", "@misc{before}\n@misc{between}\n@misc{after}\n"
    )
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert "Overleaf sync record not used" in pulled.output
    assert (project / "paper/main.tex").read_text() == "publication two\n"
    assert (project / "paper/references.bib").read_text() == (
        "@misc{before}\n@misc{between}\n@misc{after}\n"
    )


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_base_move_keeping_workspace_text_in_a_conflict_is_accepted(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    (project / "paper/main.tex").write_text("workspace\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    overleaf_edit(seed, "main.tex", "collaborator\n")
    assert run(project, "pull").exit_code == module.CONFLICT_EXIT
    # A person resolves the conflict by keeping the workspace's text.
    (project / "paper/main.tex").write_text("workspace\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    overleaf_edit(seed, "references.bib", "@misc{later}\n")
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert (project / "paper/main.tex").read_text() == "workspace\n"
    assert (project / "paper/references.bib").read_text() == "@misc{later}\n"


@pytest.mark.parametrize(
    "message", ["Invalid record. Restore it.", "History missing.\nFetch it."]
)
def test_sync_refusal_is_one_line_with_recovery_link(message):
    error = module.SyncError(message)
    assert "\n" not in error.format_message()
    assert module.RECOVERY in error.format_message()
    assert (
        module.SyncError(error.format_message()).format_message()
        == error.format_message()
    )


def test_commit_helpers_treat_option_like_revisions_as_data(setup):
    _, project = setup
    assert module.resolve_commit(project, "--all") is None
    with pytest.raises(module.GitCommandError):
        module.is_ancestor(project, "--fork-point", "HEAD")


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize(
    "legacy", ["short-base", "invalid-url", "missing-base", "invalid-json"]
)
@pytest.mark.parametrize("command", [("pull",), ("publish", "--dry-run")])
def test_invalid_historical_config_can_be_restored_in_a_new_commit(
    setup, legacy, command
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    path = project / ".asta/overleaf/paper.json"
    original = path.read_text()
    config = json.loads(original)
    if legacy == "short-base":
        config["base"] = config["base"][:12]
    elif legacy == "invalid-url":
        config["url"] = "https://legacy.example/project"
    elif legacy == "missing-base":
        config["base"] = "a" * 40
    path.write_text("{" if legacy == "invalid-json" else json.dumps(config))
    commit_all(project)
    path.write_text(original)
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    result = run(project, *command, merge=False)
    assert result.exit_code == 0, result.output
    overleaf_edit(seed, "main.tex", "edit after restoring config\n")
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert (project / "paper/main.tex").read_text() == "edit after restoring config\n"


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("gap", ["unlink", "other-project"])
def test_relink_accepts_conflict_resolved_with_workspace_text(setup, gap):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    path = project / ".asta/overleaf/paper.json"
    config = json.loads(path.read_text())
    (project / "paper/main.tex").write_text("chosen workspace resolution\n")
    commit_all(project)
    overleaf_edit(seed, "main.tex", "conflicting collaborator edit\n")
    if gap == "unlink":
        path.unlink()
    else:
        path.write_text(
            json.dumps({**config, "url": "https://git.overleaf.com/7654321"})
        )
    commit_all(project)
    config["base"] = git(seed, "rev-parse", "HEAD")
    path.write_text(json.dumps(config))
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    for command in (("publish", "--dry-run"), ("pull",)):
        result = run(project, *command, merge=False)
        assert result.exit_code == 0, result.output
    assert (project / "paper/main.tex").read_text() == "chosen workspace resolution\n"


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("missing", [False, True])
def test_pull_uses_counting_record_when_committed_base_is_unusable(setup, missing):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    # A missing base, or an existing commit outside the project's branch,
    # must not strand a paper when a verified publication record is usable.
    if missing:
        base = "0" * 40
    else:
        git(seed, "switch", "--orphan", "unrelated")
        (seed / "unrelated.tex").write_text("unrelated\n")
        commit_all(seed)
        base = git(seed, "rev-parse", "HEAD")
        git(seed, "push", "origin", "unrelated")
        git(seed, "switch", "master")
        git(seed, "pull", "--ff-only", "origin", "master")
    path = project / ".asta/overleaf/paper.json"
    config = json.loads(path.read_text())
    path.write_text(json.dumps({**config, "base": base}))
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    overleaf_edit(seed, "references.bib", "@misc{collaborator}\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert "starting from the published sync record instead" in result.output
    assert (project / "paper/main.tex").read_text() == "publication\n"
    assert (project / "paper/references.bib").read_text() == "@misc{collaborator}\n"


def newer_format():
    return {"format": module.FORMAT + 1, "requires_asta": "9.9.9"}


def test_older_cli_stops_on_newer_config_format(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    config = project / ".asta/overleaf/paper.json"
    data = json.loads(config.read_text())
    config.write_text(json.dumps({**data, **newer_format(), "base": None}))
    commit_all(project)
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    for command in (("pull",), ("publish",)):
        result = run(project, *command, merge=False)
        assert result.exit_code == 1, result.output
        assert f"sync format {module.FORMAT + 1}" in result.output
        assert "Upgrade to asta 9.9.9 or later" in result.output
        assert "Invalid sync record" not in result.output
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before


def test_newer_format_without_release_still_stops(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    config = project / ".asta/overleaf/paper.json"
    data = json.loads(config.read_text())
    config.write_text(json.dumps({**data, "format": 99, "requires_asta": "$(x)"}))
    result = run(project, "pull")
    assert result.exit_code == 1, result.output
    assert "Upgrade to a newer asta release" in result.output


def test_unversioned_config_reads_as_format_one_without_rewrite(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    config = project / ".asta/overleaf/paper.json"
    data = json.loads(config.read_text())
    legacy = json.dumps({"url": data["url"], "base": data["base"]}, indent=2) + "\n"
    config.write_text(legacy)
    commit_all(project)
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert config.read_text() == legacy
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert json.loads(config.read_text())["format"] == module.FORMAT


def test_older_cli_never_replaces_a_newer_format_record(setup, tmp_path):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    (project / "paper/main.tex").write_text("first publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    commit, data = origin_record(tmp_path)
    origin = tmp_path / "workspace.git"
    newer = forge_record(origin, {**data, **newer_format()}, commit)
    git(origin, "update-ref", RECORD_REF, newer)
    (project / "paper/main.tex").write_text("second publication\n")
    commit_all(project)
    for command in ("publish", "pull"):
        result = run(project, command)
        assert result.exit_code == 1, result.output
        assert "Upgrade to asta 9.9.9 or later" in result.output
        assert git(origin, "rev-parse", RECORD_REF) == newer


def record_file(root):
    """The pairing record of `root/paper`, inside a fresh Git workspace."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "paper").mkdir(exist_ok=True)
    path = root / ".asta/overleaf/paper.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
@pytest.mark.parametrize("directory", ["paper", "nested/paper"])
@pytest.mark.parametrize("git_file", [False, True])
def test_config_uses_same_record_through_symlinked_workspace_ancestor(
    tmp_path, directory, git_file
):
    physical = tmp_path / "physical"
    root = physical / "workspace"
    root.mkdir(parents=True)
    options = ["--separate-git-dir", str(physical / "git-metadata")] if git_file else []
    git(root, "init", "-q", *options)
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)
    paper = alias / "workspace" / directory
    record = root / f".asta/overleaf/{directory}.json"

    assert module.load_config(paper) == {}
    module.save_config(paper, URL, "a" * 40)
    assert record.is_file()
    assert not (paper / "overleaf.json").exists()
    assert module.load_config(paper) == module.load_config(root / directory)
    assert module.load_config(paper)["base"] == "a" * 40
    module.save_config(root / directory, URL, "b" * 40)
    assert module.load_config(paper)["base"] == "b" * 40


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
@pytest.mark.parametrize(
    "parent", [".asta", ".asta/overleaf", ".asta/overleaf/examples"]
)
@pytest.mark.parametrize("dangling", [False, True])
@pytest.mark.parametrize("operation", ["load", "save"])
def test_config_refuses_symlinked_parent(tmp_path, parent, dangling, operation):
    root = tmp_path / "workspace"
    record_file(root)
    paper = root / "examples/paper"
    paper.mkdir(parents=True)
    link = root / parent
    if link.exists():
        shutil.rmtree(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    if not dangling:
        outside.mkdir()
        (outside / "sentinel").write_text("unchanged\n")
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(module.SyncError, match="symlink"):
        if operation == "load":
            module.load_config(paper)
        else:
            module.save_config(paper, URL, "a" * 40)
    assert link.is_symlink()
    if dangling:
        assert not outside.exists()
    else:
        assert list(outside.iterdir()) == [outside / "sentinel"]
        assert (outside / "sentinel").read_text() == "unchanged\n"


@pytest.mark.parametrize("change_base", [False, True])
def test_save_config_refuses_newer_format_without_loading(tmp_path, change_base):
    path = record_file(tmp_path)
    data = {**newer_format(), "url": URL, "base": "a" * 40, "future": "retained"}
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    with pytest.raises(module.NewerFormatError, match="Upgrade to asta 9.9.9"):
        module.save_config(
            tmp_path / "paper", URL, "b" * 40 if change_base else data["base"]
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize("change_base", [False, True])
@pytest.mark.parametrize("dangling", [False, True])
def test_save_config_refuses_symlink_without_reading_or_writing(
    tmp_path, change_base, dangling
):
    target = tmp_path / "outside.json"
    data = {"url": URL, "base": "a" * 40}
    original = json.dumps(data)
    if not dangling:
        target.write_text(original)
    path = record_file(tmp_path)
    path.symlink_to(target)
    with pytest.raises(module.SyncError, match="is a symlink"):
        module.save_config(
            tmp_path / "paper", URL, "b" * 40 if change_base else data["base"]
        )
    assert path.is_symlink()
    if dangling:
        assert not target.exists()
    else:
        assert target.read_text() == original


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires no-follow opens")
@pytest.mark.parametrize("swap", ["before_open", "after_open"])
@pytest.mark.parametrize("operation", ["load", "save"])
def test_config_never_follows_a_racing_symlink(tmp_path, monkeypatch, swap, operation):
    path = record_file(tmp_path)
    path.write_text(json.dumps({"url": URL, "base": "a" * 40}))
    target = tmp_path / "outside.json"
    original = json.dumps({**newer_format(), "url": URL, "base": "c" * 40})
    target.write_text(original)
    real_open = module.os.open
    swapped = False

    def replace_with_link():
        nonlocal swapped
        path.unlink()
        path.symlink_to(target)
        swapped = True

    def racing_open(name, flags, *args, **kwargs):
        if Path(name) != path and not (
            Path(name) == Path(path.name) and kwargs.get("dir_fd") is not None
        ):
            return real_open(name, flags, *args, **kwargs)
        if swap == "before_open":
            replace_with_link()
            return real_open(name, flags, *args, **kwargs)
        descriptor = real_open(name, flags, *args, **kwargs)
        replace_with_link()
        return descriptor

    monkeypatch.setattr(module.os, "open", racing_open)

    def access():
        if operation == "save":
            module.save_config(tmp_path / "paper", URL, "b" * 40)
        else:
            assert module.load_config(tmp_path / "paper")["base"] == "a" * 40

    if swap == "before_open":
        with pytest.raises(module.SyncError, match="is a symlink"):
            access()
    else:
        access()
    assert swapped
    assert path.is_symlink()
    assert target.read_text() == original


@pytest.mark.skipif(os.name == "nt", reason="requires directory-relative opens")
@pytest.mark.parametrize("swap", ["before_directory_open", "before_file_open"])
@pytest.mark.parametrize("operation", ["load", "save"])
def test_config_never_follows_a_racing_parent_symlink(
    tmp_path, monkeypatch, swap, operation
):
    root = tmp_path / "workspace"
    path = record_file(root)
    path.write_text(json.dumps({"url": URL, "base": "a" * 40}))
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / path.name
    original = json.dumps({"url": URL, "base": "c" * 40})
    target.write_text(original)
    real_open = module.os.open
    swapped = False

    def racing_open(name, flags, *args, **kwargs):
        nonlocal swapped
        trigger = "overleaf" if swap == "before_directory_open" else path.name
        if not swapped and name == trigger and kwargs.get("dir_fd") is not None:
            path.parent.rename(path.parent.with_name("original"))
            path.parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", racing_open)

    def access():
        if operation == "save":
            module.save_config(root / "paper", URL, "b" * 40)
        else:
            assert module.load_config(root / "paper")["base"] == "a" * 40

    if swap == "before_directory_open":
        with pytest.raises(module.SyncError, match="symlink"):
            access()
    else:
        access()
        saved = json.loads((path.parent.with_name("original") / path.name).read_text())
        assert saved["base"] == ("b" if operation == "save" else "a") * 40
    assert swapped
    assert target.read_text() == original


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
@pytest.mark.parametrize("operation", ["load", "save"])
@pytest.mark.parametrize("target", ["outside", "inside", "missing"])
def test_config_refuses_symlinked_paper_path(tmp_path, operation, target):
    root = tmp_path / "workspace"
    record_file(root)
    destination = root / "inside" if target == "inside" else tmp_path / target
    if target != "missing":
        destination.mkdir()
    paper = root / "examples/paper"
    paper.parent.mkdir()
    paper.symlink_to(destination, target_is_directory=True)
    with pytest.raises(module.SyncError, match="symlinked directory"):
        if operation == "save":
            module.save_config(paper, URL, "a" * 40)
        else:
            module.load_config(paper)
    assert not list((root / ".asta/overleaf").rglob("*.json"))
    if target == "missing":
        assert not destination.exists()
    else:
        assert not list(destination.iterdir())


def test_save_validates_record_parents_before_creating_paper(tmp_path):
    record_file(tmp_path)
    shutil.rmtree(tmp_path / ".asta/overleaf")
    (tmp_path / ".asta/overleaf").symlink_to(
        tmp_path / "missing", target_is_directory=True
    )
    paper = tmp_path / "new/paper"
    with pytest.raises(module.SyncError, match="symlink"):
        module.save_config(paper, URL, "a" * 40)
    assert not paper.parent.exists()
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("stamped", [False, True])
def test_unchanged_config_preserves_extra_fields_and_formatting(tmp_path, stamped):
    path = record_file(tmp_path)
    data = {"url": URL, "base": "a" * 40, "extra": {"retained": True}}
    if stamped:
        data.update(module.format_stamp())
    original = json.dumps(data, indent=4) + "\n\n"
    path.write_text(original)
    before = path.stat().st_mtime_ns
    module.save_config(tmp_path / "paper", URL, data["base"])
    assert path.read_text() == original
    assert path.stat().st_mtime_ns == before


@pytest.mark.parametrize("stamped", [False, True])
@pytest.mark.parametrize("change", ["base", "url", "both"])
def test_changed_config_preserves_unknown_fields(tmp_path, stamped, change):
    path = record_file(tmp_path)
    data = {
        "url": URL,
        "base": "a" * 40,
        "future": {"enabled": True, "options": [1, None, "value"]},
        "optional": None,
    }
    if stamped:
        data.update(module.format_stamp())
    path.write_text(json.dumps(data))
    url = "https://git.overleaf.com/7654321" if change in {"url", "both"} else URL
    base = "b" * 40 if change in {"base", "both"} else data["base"]
    module.save_config(tmp_path / "paper", url, base)
    assert json.loads(path.read_text()) == {
        **data,
        **module.format_stamp(),
        "url": url,
        "base": base,
    }


def test_pull_preserves_unknown_config_fields_when_base_changes(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    path = project / ".asta/overleaf/paper.json"
    data = json.loads(path.read_text())
    data["future"] = {"retained": [True, None]}
    path.write_text(json.dumps(data))
    commit_all(project)
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    saved = json.loads(path.read_text())
    assert saved["base"] != data["base"]
    assert saved["future"] == data["future"]


@pytest.mark.parametrize("version", [0, None])
@pytest.mark.parametrize("change_base", [False, True])
def test_save_config_refuses_invalid_format_without_overwriting(
    tmp_path, version, change_base
):
    path = record_file(tmp_path)
    path.write_text(json.dumps({"format": version, "url": URL, "base": "a" * 40}))
    before = path.read_bytes()
    with pytest.raises(module.FormatError, match="malformed sync format stamp"):
        module.save_config(tmp_path / "paper", URL, ("b" if change_base else "a") * 40)
    assert path.read_bytes() == before


def test_null_config_format_refuses_before_copying_or_publishing(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    config = project / ".asta/overleaf/paper.json"
    data = json.loads(config.read_text())
    config.write_text(json.dumps({**data, "format": None}))
    commit_all(project)
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    origin_refs = git(project, "ls-remote", "origin")
    overleaf_refs = git(seed, "ls-remote", "origin")
    for command in ("pull", "publish"):
        result = run(project, command, merge=False)
        assert result.exit_code == 1, result.output
        assert "malformed sync format stamp" in result.output
        assert isinstance(result.exception, SystemExit)
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before
    assert git(project, "ls-remote", "origin") == origin_refs
    assert git(seed, "ls-remote", "origin") == overleaf_refs


def test_record_format_distinguishes_missing_from_null(setup, tmp_path):
    _, project = setup
    origin = tmp_path / "workspace.git"
    legacy = {"url": URL, "overleaf": "a" * 40, "workspace": "b" * 40}
    commit = forge_record(origin, legacy)
    assert module.read_record(origin, commit, url=URL) == legacy
    commit = forge_record(origin, {**legacy, "format": None})
    with pytest.raises(module.FormatError, match="malformed sync format stamp"):
        module.read_record(origin, commit, url=URL)


@pytest.mark.parametrize("version", [None, 0])
def test_invalid_record_format_refuses_instead_of_falling_back(
    setup, tmp_path, version
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("first publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    commit, data = origin_record(tmp_path)
    origin = tmp_path / "workspace.git"
    invalid = forge_record(origin, {**data, "format": version}, commit)
    git(origin, "update-ref", RECORD_REF, invalid)
    (project / "paper/main.tex").write_text("second publication\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    origin_refs = git(project, "ls-remote", "origin")
    overleaf_refs = git(seed, "ls-remote", "origin")
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    for command in ("pull", "publish"):
        result = run(project, command, merge=False)
        assert result.exit_code == 1, result.output
        assert "malformed sync format stamp" in result.output
        assert "record not used" not in result.output
        assert isinstance(result.exception, SystemExit)
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before
    assert git(project, "ls-remote", "origin") == origin_refs
    assert git(seed, "ls-remote", "origin") == overleaf_refs


@pytest.mark.parametrize(
    "results, code, outcome",
    [
        (["waiting", "locked", "complete"], 0, "Sync outcome: complete."),
        (["waiting", "person"], 4, "Sync outcome: a person must act."),
        (["waiting"] * 50, 5, "Sync outcome: still waiting; rerun sync to continue."),
    ],
)
def test_sync_wait_reruns_until_complete_or_a_person_must_act(
    setup, monkeypatch, results, code, outcome
):
    _, project = setup
    assert run(project, "pull", URL, "--dir", "paper").exit_code == 0
    commit_all(project)
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    clock = [0.0]
    calls = []

    def fake_sync(_, directory, **kwargs):
        calls.append(directory)
        state = results[len(calls) - 1]
        return state, f"fixture {state}"

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    monkeypatch.setattr(module, "_sync_monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module, "_sync_sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    result = run(project, "sync", "--wait", "300")
    assert result.exit_code == code, result.output
    last = result.output.strip().splitlines()[-1]
    assert last.startswith(outcome)
    if code == 5:
        # The last sleep reaches the deadline without starting another attempt.
        assert clock[0] == 300
        assert len(calls) == 10
    else:
        assert len(calls) == len(results)


def test_sync_wait_reports_refusal_as_operator_outcome(setup, monkeypatch):
    _, project = setup
    assert run(project, "pull", URL, "--dir", "paper").exit_code == 0
    commit_all(project)
    sync_module = importlib.import_module("asta.commands.overleaf_sync")

    def refuse(*_, **kwargs):
        raise module.SyncError("fixture refusal")

    monkeypatch.setattr(sync_module, "sync_workspace", refuse)
    result = run(project, "sync", "--wait", "60")
    assert result.exit_code == 1, result.output
    assert (
        "Sync outcome: failed; an operator must act. fixture refusal" in result.output
    )


def test_plain_sync_exit_codes_are_unchanged_by_outcomes(setup, monkeypatch):
    _, project = setup
    assert run(project, "pull", URL, "--dir", "paper").exit_code == 0
    commit_all(project)
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    monkeypatch.setattr(
        sync_module, "sync_workspace", lambda *_: ("person", "fixture person")
    )
    result = run(project, "sync")
    assert result.exit_code == 0, result.output
    assert "Sync outcome" not in result.output


@pytest.mark.parametrize(
    "first_state, code", [("waiting", 5), ("complete", 5), ("person", 4), ("failed", 1)]
)
def test_sync_wait_does_not_start_later_papers_after_deadline(
    tmp_path, monkeypatch, first_state, code
):
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    gate = importlib.import_module("asta.commands.overleaf_gate")
    clock = [0.0]
    calls = []
    checks = []
    monkeypatch.setattr(
        module, "paired_directories", lambda _: ["first", "second", "third"]
    )
    monkeypatch.setattr(module, "_sync_monotonic", lambda: clock[0])
    monkeypatch.setattr(
        gate, "require_release_check", lambda *args: checks.append(args[1])
    )

    def fake_sync(_, directory, **kwargs):
        calls.append(directory)
        clock[0] = 60.0
        if first_state == "failed":
            raise module.SyncError("fixture refusal")
        return first_state, "fixture result"

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", "--wait", "60", "--check-repo", "allenai/test")
    assert result.exit_code == code, result.output
    assert calls == checks == ["first"]
    for directory in ("second", "third"):
        assert (
            f"{directory}: Sync outcome: still waiting; rerun sync to continue."
            in result.output
        )
    assert result.output.count("Sync outcome:") == 3


@pytest.mark.parametrize("wait", [0, 60])
@pytest.mark.parametrize("discovery_seconds", [60, 61])
def test_sync_wait_checks_deadline_after_discovering_papers(
    tmp_path, monkeypatch, wait, discovery_seconds
):
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    gate = importlib.import_module("asta.commands.overleaf_gate")
    clock = [0.0]
    calls, checks = [], []

    def discover(_):
        clock[0] += discovery_seconds
        return ["first", "second"]

    monkeypatch.setattr(module, "paired_directories", discover)
    monkeypatch.setattr(module, "_sync_monotonic", lambda: clock[0])
    monkeypatch.setattr(
        gate, "require_release_check", lambda *args: checks.append(args[1])
    )

    def fake_sync(_, directory, **kwargs):
        calls.append(directory)
        return "complete", "fixture result"

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", "--wait", str(wait), "--check-repo", "allenai/test")
    assert result.exit_code == (0 if wait == 0 else 5), result.output
    assert calls == checks == (["first", "second"] if wait == 0 else [])
    assert result.output.count("Sync outcome:") == 2
    if wait:
        assert result.output.count("Wait deadline reached before this paper") == 2


def test_sync_wait_zero_attempts_each_paper_once(tmp_path, monkeypatch):
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    calls = []
    monkeypatch.setattr(module, "paired_directories", lambda _: ["first", "second"])
    monkeypatch.setattr(module, "_sync_monotonic", lambda: 0.0)

    def fake_sync(_, directory, **kwargs):
        calls.append(directory)
        return "waiting", "fixture result"

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", "--wait", "0")
    assert result.exit_code == 5, result.output
    assert calls == ["first", "second"]
    assert result.output.count("Sync outcome:") == 2


def test_sync_wait_visits_other_papers_before_retrying(tmp_path, monkeypatch):
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    gate = importlib.import_module("asta.commands.overleaf_gate")
    clock = [0.0]
    calls, checks, sleeps = [], [], []
    monkeypatch.setattr(module, "paired_directories", lambda _: ["first", "second"])
    monkeypatch.setattr(module, "_sync_monotonic", lambda: clock[0])
    monkeypatch.setattr(
        gate, "require_release_check", lambda *args: checks.append(args[1:])
    )

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    def fake_sync(_, directory, **kwargs):
        calls.append(directory)
        state = "waiting" if directory == "first" and len(calls) == 1 else "complete"
        return state, "fixture result"

    monkeypatch.setattr(module, "_sync_sleep", sleep)
    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", "--wait", "60", "--check-repo", "allenai/test")
    assert result.exit_code == 0, result.output
    assert calls == ["first", "second", "first"]
    assert checks == [("first", "allenai/test", 60), ("second", "allenai/test", 60)]
    assert sleeps == [30]
    assert result.output.count("Sync outcome: complete.") == 2


def test_sync_wait_stops_after_release_check_consumes_deadline(tmp_path, monkeypatch):
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    gate = importlib.import_module("asta.commands.overleaf_gate")
    clock = [0.0]
    calls, checks = [], []
    monkeypatch.setattr(module, "paired_directories", lambda _: ["first", "second"])
    monkeypatch.setattr(module, "_sync_monotonic", lambda: clock[0])

    def check(*args):
        checks.append(args[1:])
        clock[0] = 60.0

    monkeypatch.setattr(gate, "require_release_check", check)
    monkeypatch.setattr(
        sync_module, "sync_workspace", lambda *args, **kwargs: calls.append(args)
    )
    result = run(tmp_path, "sync", "--wait", "60", "--check-repo", "allenai/test")
    assert result.exit_code == 5, result.output
    assert checks == [("first", "allenai/test", 60)]
    assert calls == []
    assert result.output.count("Sync outcome: still waiting") == 2


@pytest.mark.parametrize("failure", ["os", "json", "subprocess", "none", "format"])
def test_sync_wait_reports_errors_and_continues_other_papers(
    tmp_path, monkeypatch, failure
):
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    calls = []
    monkeypatch.setattr(module, "paired_directories", lambda _: ["first", "second"])

    def fake_sync(_, directory, **kwargs):
        calls.append(directory)
        if directory == "second":
            return "complete", "fixture result"
        if failure == "os":
            raise OSError("fixture-private-transport-detail\nextra line")
        if failure == "json":
            raise json.JSONDecodeError("fixture-private-transport-detail", "", 0)
        if failure == "subprocess":
            raise subprocess.SubprocessError("fixture-private-transport-detail")
        if failure == "format":
            raise module.FormatError("fixture format refusal")
        return None

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", "--wait", "60")
    assert result.exit_code == 1, result.output
    assert calls == ["first", "second"]
    assert result.output.count("Sync outcome:") == 2
    assert "first: Sync outcome: failed; an operator must act." in result.output
    assert "second: Sync outcome: complete." in result.output
    assert "fixture-private-transport-detail" not in result.output
    assert (
        "fixture format refusal" in result.output
        if failure == "format"
        else "Unexpected" in result.output
    )


def test_sync_wait_reports_directory_discovery_failure(tmp_path, monkeypatch):
    def refuse(_):
        raise module.SyncError("fixture invalid pairing")

    monkeypatch.setattr(module, "paired_directories", refuse)
    result = run(tmp_path, "sync", "--wait", "60")
    assert result.exit_code == 1, result.output
    assert (
        "Sync outcome: failed; an operator must act. fixture invalid pairing"
        in result.output
    )


def test_sync_wait_does_not_swallow_interrupt(tmp_path, monkeypatch):
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    monkeypatch.setattr(module, "paired_directories", lambda _: ["first", "second"])

    def interrupt(*_, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(sync_module, "sync_workspace", interrupt)
    result = run(tmp_path, "sync", "--wait", "60")
    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert "Sync outcome:" not in result.output


@pytest.mark.parametrize("wait", [None, "0"])
def test_sync_wait_disables_git_prompts_even_in_a_terminal(tmp_path, monkeypatch, wait):
    sync_module = importlib.import_module("asta.commands.overleaf_sync")
    environments = []
    monkeypatch.setattr(module, "paired_directories", lambda _: ["paper"])
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    monkeypatch.setenv("GIT_ASKPASS", "fixture-askpass")
    monkeypatch.setenv("SSH_ASKPASS", "fixture-ssh-askpass")
    monkeypatch.delenv("SSH_ASKPASS_REQUIRE", raising=False)
    monkeypatch.setenv("GIT_SSH_COMMAND", 'ssh -i "$HOME/key with spaces"')
    monkeypatch.setenv("GH_PROMPT_DISABLED", "0")

    def fake_sync(*_, **kwargs):
        monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
        environments.append(module.git_environment())
        return "complete", "fixture result"

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", *([] if wait is None else ["--wait", wait]))
    assert result.exit_code == 0, result.output
    env = environments[0]
    assert env["GIT_TERMINAL_PROMPT"] == ("1" if wait is None else "0")
    assert env["GIT_ASKPASS"] == ("fixture-askpass" if wait is None else "")
    assert env["SSH_ASKPASS"] == ("fixture-ssh-askpass" if wait is None else "")
    assert env.get("SSH_ASKPASS_REQUIRE") == (None if wait is None else "never")
    # The person's SSH command and Git config are left exactly as written.
    assert env["GIT_SSH_COMMAND"] == 'ssh -i "$HOME/key with spaces"'
    assert env["GH_PROMPT_DISABLED"] == ("0" if wait is None else "1")


@pytest.mark.parametrize("wait", [False, True])
def test_sync_wait_runs_git_with_no_terminal(tmp_path, monkeypatch, wait):
    calls = []
    real_run = subprocess.run

    def recording_run(*args, **kwargs):
        calls.append(kwargs)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", recording_run)
    with click.Context(click.Command("sync")) as ctx:
        ctx.meta["overleaf_noninteractive"] = wait
        module.git_bytes("--version", cwd=tmp_path)
        module.git_bytes("hash-object", "--stdin", cwd=tmp_path, input=b"x")
    plain, with_input = calls
    if wait:
        assert plain["stdin"] is subprocess.DEVNULL
        assert "stdin" not in with_input
        assert plain["start_new_session"] is (os.name == "posix")
    else:
        assert "stdin" not in plain and "start_new_session" not in plain


@pytest.mark.skipif(os.name != "posix", reason="needs POSIX sessions")
def test_sync_wait_ssh_cannot_reach_a_terminal(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    ssh = tmp_path / "fixture-ssh"
    ssh.write_text(
        "#!/bin/sh\n"
        'if (exec </dev/tty) 2>/dev/null; then echo terminal >"$MARKER";'
        ' else echo none >"$MARKER"; fi\n'
        "exit 255\n"
    )
    ssh.chmod(0o755)
    monkeypatch.setenv("MARKER", str(marker))
    monkeypatch.setenv("GIT_SSH_COMMAND", str(ssh))
    with click.Context(click.Command("sync")) as ctx:
        ctx.meta["overleaf_noninteractive"] = True
        with pytest.raises(click.ClickException):
            module.git_bytes("ls-remote", "ssh://fixture.invalid/paper", cwd=tmp_path)
    assert marker.read_text() == "none\n"
