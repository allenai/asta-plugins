"""Tests for `asta workspace overleaf pull|publish` against a local bare remote."""

import importlib
import json
import os
import shutil
import subprocess

import pytest
from click.testing import CliRunner

from asta.cli import cli

module = importlib.import_module("asta.commands.overleaf")
REAL_GIT_BYTES = module.git_bytes
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
    remote = tmp_path / "overleaf.git"
    original_git = REAL_GIT_BYTES

    def transport(*args, **kwargs):
        if "--get-url" in args:
            return (URL + "\n").encode()
        return original_git(
            *(str(remote) if arg == URL else arg for arg in args), **kwargs
        )

    monkeypatch.setattr(module, "git_bytes", transport)
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
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    paper = project / "paper"
    assert (paper / "main.tex").read_text() == "hello\n"
    assert not (paper / "references.bib").exists()
    config = json.loads((paper / "overleaf.json").read_text())
    assert config["url"] == URL and len(config["base"]) == 40


@pytest.mark.parametrize(
    "scope", ["", ".https://git.overleaf.com", ".https://git.overleaf.com/1234567"]
)
def test_token_disables_real_credential_storage(setup, monkeypatch, tmp_path, scope):
    _, _, project = setup
    stored = tmp_path / "credentials"
    global_config = tmp_path / "gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    git(
        project,
        "config",
        "--global",
        f"credential{scope}.helper",
        f"store --file={stored}",
    )
    git(project, "config", "--global", "credential.useHttpPath", "true")
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    credential = b"protocol=https\nhost=git.overleaf.com\npath=1234567\nusername=git\npassword=fixture-token\n\n"
    # Demonstrate that the configured helper really would save a credential.
    module.git("credential", "approve", cwd=project, data=credential)
    assert stored.exists()
    stored.unlink()
    with module.credentials() as env:
        module.git(
            *module.network_options(env, project),
            "credential",
            "approve",
            cwd=project,
            env=env,
            data=credential,
        )
    assert not stored.exists()


@pytest.mark.parametrize(
    ("operation", "diagnostic", "message"),
    [
        (
            "fetch",
            b"Authentication failed for https://git:fixture-token@git.overleaf.com",
            "authentication failed",
        ),
        (
            "push",
            b"[rejected] master -> master (fetch first) fixture-token",
            "changed during publish",
        ),
    ],
)
def test_git_errors_are_actionable_without_credentials(
    setup, monkeypatch, operation, diagnostic, message
):
    _, _, project = setup
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 128, b"", diagnostic
        ),
    )
    with pytest.raises(module.click.ClickException) as error:
        REAL_GIT_BYTES(operation, URL, cwd=project)
    assert message in str(error.value)
    assert "fixture-token" not in str(error.value)


def test_ignore_check_failure_is_not_reported_as_missing_rule(setup, monkeypatch):
    _, _, project = setup
    original = subprocess.run

    def fail_check(*args, **kwargs):
        if "check-ignore" in args[0]:
            return subprocess.CompletedProcess(args[0], 128, b"", b"fixture-token")
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_check)
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "Cannot check" in result.output
    assert "fixture-token" not in result.output
    assert "Ignore .asta/cache" not in result.output


def test_git_uses_an_empty_hooks_directory(setup, tmp_path):
    _, _, project = setup
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    marker = tmp_path / "hook-ran"
    hook = hooks / "pre-commit"
    hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    hook.chmod(0o700)
    git(project, "config", "core.hooksPath", str(hooks))
    git(project, "config", "user.name", "fixture writer")
    git(project, "config", "user.email", "fixture@example.invalid")
    module.git("commit", "--allow-empty", "-m", "fixture", cwd=project)
    assert not marker.exists()


def test_real_global_url_rewrite_is_rejected(setup, monkeypatch, tmp_path):
    _, _, project = setup
    config = tmp_path / "gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    git(
        project,
        "config",
        "--global",
        "url.https://example.invalid/.insteadOf",
        "https://git.overleaf.com/",
    )
    monkeypatch.setattr(module, "git_bytes", REAL_GIT_BYTES)
    original_run = subprocess.run

    def deny_network(*args, **kwargs):
        command = args[0]
        if "ls-remote" in command and "--get-url" not in command:
            pytest.fail("network attempted")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", deny_network)
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "URL rewrites" in result.output


@pytest.mark.parametrize(
    "names", [("Fig.png", "fig.png"), ("Figures/a.png", "figures/b.png")]
)
def test_case_only_remote_paths_stop_before_import(setup, names):
    _, seed, project = setup
    for name in names:
        target = seed / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b"figure")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "case collision")
    git(seed, "push", "origin", "master")
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "Case-only" in result.output
    assert not (project / "paper").exists()


@pytest.mark.parametrize("existing_import", [False, True])
@pytest.mark.parametrize(
    "names",
    [
        ("fig.png", "Fig.png"),
        ("figures/a.png", "Figures/b.png"),
        ("figure", "Figure/a.png"),
    ],
)
def test_case_only_merged_paths_stop_before_writing(setup, names, existing_import):
    _, seed, project = setup
    paper = imported(project) if existing_import else project / "paper"
    local_name, remote_name = names
    local = paper / local_name
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"local figure")
    git(project, "add", "paper")
    git(project, "commit", "-m", "local figure")
    before = {
        path.relative_to(paper): path.read_bytes()
        for path in paper.rglob("*")
        if path.is_file()
    }
    (seed / remote_name).parent.mkdir(parents=True, exist_ok=True)
    overleaf_edit(seed, remote_name, "remote figure\n")
    overleaf_edit(seed, "main.tex", "updated paper\n")

    result = run(project, "pull", URL)

    assert result.exit_code == 1 and "Case-only" in result.output
    assert {
        path.relative_to(paper): path.read_bytes()
        for path in paper.rglob("*")
        if path.is_file()
    } == before
    assert git(project, "status", "--porcelain") == ""


@pytest.mark.parametrize("args", [("pull",), ("pull", "--reconcile-bibliography")])
def test_deleted_worktree_bibliography_is_not_reimported(setup, args):
    _, _, project = setup
    paper = imported(project)
    before = (paper / module.CONFIG).read_bytes()
    (project / "references.bib").unlink()
    result = run(project, *args)
    assert result.exit_code == 1 and "references.bib" in result.output
    assert not (project / "references.bib").exists()
    assert (paper / module.CONFIG).read_bytes() == before


def test_normal_pull_refuses_uncommitted_root_bibliography(setup):
    _, seed, project = setup
    paper = imported(project)
    (project / "references.bib").write_text("@misc{local}\n")
    overleaf_edit(seed, "main.tex", "new paper\n")
    result = run(project, "pull")
    assert result.exit_code == 1 and "uncommitted changes" in result.output
    assert (paper / "main.tex").read_text() == "hello\n"
    assert (project / "references.bib").read_text() == "@misc{local}\n"


def test_crlf_bibliography_does_not_produce_false_backup(setup):
    _, _, project = setup
    imported(project)
    (project / ".gitattributes").write_text("references.bib text eol=crlf\n")
    git(project, "add", ".gitattributes")
    git(project, "commit", "-m", "CRLF checkout")
    (project / "references.bib").unlink()
    git(project, "restore", "references.bib")
    assert (project / "references.bib").read_bytes() == b"@misc{a}\r\n"
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert "Reconcile needed entries" not in result.output
    assert not list((project / ".asta/cache").rglob("overleaf-references.bib"))


def test_missing_base_has_reimport_guidance(setup):
    _, _, project = setup
    paper = imported(project)
    metadata = paper / module.CONFIG
    config = json.loads(metadata.read_text())
    config["base"] = "a" * 40
    metadata.write_text(json.dumps(config))
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "-m", "missing base")
    result = run(project, "pull")
    assert result.exit_code == 1 and "re-import" in result.output
    assert isinstance(result.exception, SystemExit)
    assert (paper / "main.tex").read_text() == "hello\n"


def test_filesystem_failure_has_recovery_guidance(setup, monkeypatch):
    _, seed, project = setup
    paper = imported(project)
    git(seed, "rm", "old.tex")
    git(seed, "commit", "-m", "remove")
    git(seed, "push", "origin", "master")
    original = type(paper).unlink

    def fail(target, *args, **kwargs):
        if target == paper / "old.tex":
            raise OSError("fixture permission failure")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(type(paper), "unlink", fail)
    result = run(project, "pull")
    assert result.exit_code == 1 and "Inspect the working tree" in result.output
    assert isinstance(result.exception, SystemExit)


def test_private_file_mode_survives_atomic_replacement(tmp_path):
    target = tmp_path / "references.bib"
    target.write_bytes(b"old")
    target.chmod(0o600)
    module.replace_file(target, b"new")
    assert target.read_bytes() == b"new"
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".asta-tmp-*"))


def test_publish_uses_workspace_git_identity(setup):
    remote, _, project = setup
    paper = imported(project)
    git(project, "config", "user.name", "Fixture author")
    git(project, "config", "user.email", "author@example.invalid")
    (paper / "main.tex").write_text("reviewed\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "review")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert (
        git(remote, "log", "-1", "--format=%an <%ae>")
        == "Fixture author <author@example.invalid>"
    )


def test_publish_round_trip_and_refuses_unpulled_edits(setup):
    remote, seed, project = setup
    imported(project)
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
    assert run(project, "pull", URL).exit_code == 0
    git(project, "add", ".")
    git(project, "commit", "-m", "import")
    (project / "paper" / "main.tex").write_text("local\n")
    result = run(project, "pull")
    assert result.exit_code != 0
    assert "uncommitted changes" in result.output


def test_pull_removes_files_deleted_in_overleaf(setup):
    remote, seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
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
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper" / "main.tex").write_text("draft\n")
    git(project, "add", ".")
    git(project, "commit", "-m", "edit")
    result = run(project, "publish", "--dry-run")
    assert result.exit_code == 0 and "Dry run" in result.output
    git(seed, "pull", "origin", "master")
    assert (seed / "main.tex").read_text() == "hello\n"


def imported(project):
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    git(project, "add", "paper")
    git(project, "commit", "-m", "import")
    return project / "paper"


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/123",
        "http://git.overleaf.com/123",
        "https://git.overleaf.com.attacker.example/123",
        "ssh://git.overleaf.com/123",
        "https://git:secret@git.overleaf.com/123",
        "https://git.overleaf.com/123?secret=x",
        "https://git.overleaf.com:443/123",
        "https://git.overleaf.com/123#fragment",
        "/tmp/repo",
        "https://git.overleaf.com/../123",
    ],
)
def test_invalid_destination_never_receives_credentials(setup, monkeypatch, url):
    _, _, project = setup
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    monkeypatch.setattr(
        module, "credentials", lambda: pytest.fail("credentials accessed")
    )
    result = run(project, "pull", url)
    assert result.exit_code == 1, result.output
    assert "Other Git hosts" in result.output
    assert "secret" not in result.output and "fixture-token" not in result.output


@pytest.mark.parametrize("operation", ["pull", "publish"])
def test_committed_malicious_url_is_rejected(setup, monkeypatch, operation):
    _, _, project = setup
    paper = imported(project)
    config = json.loads((paper / module.CONFIG).read_text())
    config["url"] = "https://attacker.example/123"
    (paper / module.CONFIG).write_text(json.dumps(config))
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "-m", "bad destination")
    monkeypatch.setattr(
        module, "credentials", lambda: pytest.fail("credentials accessed")
    )
    result = run(project, operation)
    assert result.exit_code == 1 and "Other Git hosts" in result.output


def test_url_normalizes_overleaf_username():
    assert (
        module.validate_url("https://git@git.overleaf.com/abc123.git/")
        == "https://git.overleaf.com/abc123"
    )


def test_credentials_are_ephemeral_and_not_in_script(setup, monkeypatch):
    _, _, project = setup
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    with module.credentials() as env:
        from pathlib import Path

        script = Path(env["GIT_ASKPASS"])
        assert script.exists() and script.stat().st_mode & 0o777 == 0o700
        assert "fixture-token" not in script.read_text()
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert "http.followRedirects=false" in module.network_options(env, project)
        assert "credential.helper=" in module.network_options(env, project)
    assert not script.exists()


def test_forged_workspace_trailer_does_not_allow_overwrite(setup):
    remote, seed, project = setup
    imported(project)
    before = git(remote, "rev-parse", "HEAD")
    overleaf_edit(
        seed,
        "main.tex",
        "other workspace\n",
        "publish\n\nAsta-Workspace-Commit: " + "a" * 40,
    )
    after = git(remote, "rev-parse", "HEAD")
    assert before != after
    result = run(project, "publish")
    assert result.exit_code == 1 and "Overleaf has edits" in result.output
    assert git(remote, "rev-parse", "HEAD") == after


def test_pull_preserves_committed_edits_on_disjoint_files(setup):
    _, seed, project = setup
    paper = imported(project)
    (paper / "main.tex").write_text("workspace edit\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "local edit")
    overleaf_edit(seed, "old.tex", "remote edit\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (paper / "main.tex").read_text() == "workspace edit\n"
    assert (paper / "old.tex").read_text() == "remote edit\n"


@pytest.mark.parametrize("local", ["edit", "delete"])
def test_overlapping_committed_edits_stop_before_any_import(setup, local):
    _, seed, project = setup
    paper = imported(project)
    if local == "delete":
        git(project, "rm", "paper/main.tex")
    else:
        (paper / "main.tex").write_text("workspace edit\n")
        git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "local edit")
    before = {
        p.relative_to(paper): p.read_bytes() for p in paper.rglob("*") if p.is_file()
    }
    overleaf_edit(seed, "old.tex", "nonconflicting remote edit\n")
    overleaf_edit(seed, "main.tex", "overlapping remote edit\n")
    result = run(project, "pull")
    assert result.exit_code == 1 and "Both workspace and Overleaf" in result.output
    assert {
        p.relative_to(paper): p.read_bytes() for p in paper.rglob("*") if p.is_file()
    } == before
    assert git(project, "status", "--porcelain") == ""


@pytest.mark.parametrize("operation", ["pull", "publish"])
def test_tracked_paper_symlink_is_rejected(setup, operation):
    remote, _, project = setup
    paper = imported(project)
    outside = project.parent / "private.txt"
    outside.write_text("private fixture")
    (paper / "main.tex").unlink()
    (paper / "main.tex").symlink_to(outside)
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "symlink")
    before = git(remote, "rev-parse", "HEAD")
    result = run(project, operation)
    assert result.exit_code == 1 and "Symlinks" in result.output
    assert git(remote, "rev-parse", "HEAD") == before
    assert outside.read_text() == "private fixture"


def test_remote_symlink_is_not_imported(setup):
    _, seed, project = setup
    (seed / "secret.tex").symlink_to("/tmp/private.txt")
    git(seed, "add", "secret.tex")
    git(seed, "commit", "-m", "symlink")
    git(seed, "push", "origin", "master")
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "Symlinks" in result.output
    assert not (project / "paper").exists()


@pytest.mark.parametrize("staged", [False, True])
def test_unreviewed_bibliography_cannot_be_published(setup, staged):
    remote, _, project = setup
    imported(project)
    before = git(remote, "rev-parse", "HEAD")
    (project / "references.bib").write_text("@misc{unreviewed}\n")
    if staged:
        git(project, "add", "references.bib")
    result = run(project, "publish")
    assert (
        result.exit_code == 1
        and "references.bib has uncommitted changes" in result.output
    )
    assert git(remote, "rev-parse", "HEAD") == before


def test_missing_root_bibliography_is_imported_for_review(setup):
    _, _, project = setup
    git(project, "rm", "references.bib")
    git(project, "commit", "-m", "no bibliography yet")
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    assert (project / "references.bib").read_text() == "@misc{a}\n"
    assert not (project / "paper/references.bib").exists()
    assert "root references.bib for review" in result.output
    assert run(project, "publish").exit_code == 1


def test_differing_remote_bibliography_is_saved_without_overwrite(setup):
    _, seed, project = setup
    overleaf_edit(seed, "references.bib", "@misc{coauthor}\n")
    result = run(project, "pull", URL)
    assert result.exit_code == 0 and "Reconcile needed entries" in result.output
    assert (project / "references.bib").read_text() == "@misc{a}\n"
    backup = list((project / ".asta/cache").rglob("overleaf-references.bib"))
    assert len(backup) == 1 and backup[0].read_text() == "@misc{coauthor}\n"
    assert not (project / "paper/references.bib").exists()


def test_remote_default_main_branch_is_supported(setup):
    remote, seed, project = setup
    git(seed, "branch", "-m", "main")
    git(seed, "push", "origin", "main")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    paper = imported(project)
    (paper / "main.tex").write_text("reviewed main\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "edit")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert git(remote, "show", "main:main.tex") == "reviewed main"
    assert git(remote, "show", "master:main.tex") == "hello"


def test_remote_changes_after_fetch_reject_push(setup, monkeypatch):
    remote, seed, project = setup
    paper = imported(project)
    (paper / "main.tex").write_text("reviewed\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "edit")
    real_git = module.git_bytes
    advanced = []

    def race(*args, **kwargs):
        if "push" in args and URL in args:
            overleaf_edit(seed, "old.tex", "concurrent coauthor\n")
            advanced.append(git(remote, "rev-parse", "HEAD"))
        return real_git(*args, **kwargs)

    monkeypatch.setattr(module, "git_bytes", race)
    result = run(project, "publish")
    assert result.exit_code == 1 and "Overleaf changed during publish" in result.output
    assert git(remote, "rev-parse", "HEAD") == advanced[0]
    assert git(remote, "show", "HEAD:main.tex") == "hello"
    assert not list((project / ".asta/cache").rglob("published-*.json"))


def test_url_rewrite_is_rejected_before_network(setup, monkeypatch):
    _, _, project = setup
    transport = module.git_bytes

    def rewrite(*args, **kwargs):
        if "--get-url" in args:
            return b"https://attacker.example/repo\n"
        if "ls-remote" in args or "fetch" in args:
            pytest.fail("network attempted")
        return transport(*args, **kwargs)

    monkeypatch.setattr(module, "git_bytes", rewrite)
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "URL rewrites" in result.output


def test_first_import_does_not_overwrite_existing_committed_paper(setup):
    _, _, project = setup
    paper = project / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text("existing paper\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "existing paper")
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "Both workspace and Overleaf" in result.output
    assert (paper / "main.tex").read_text() == "existing paper\n"
    assert not (paper / module.CONFIG).exists()


def test_ignored_import_collision_is_not_overwritten(setup):
    _, _, project = setup
    (project / ".gitignore").write_text(".asta/cache/\npaper/main.tex\n")
    git(project, "add", ".gitignore")
    git(project, "commit", "-m", "ignore output")
    paper = project / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text("ignored local file\n")
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "untracked file blocks" in result.output
    assert (paper / "main.tex").read_text() == "ignored local file\n"
    assert not (paper / module.CONFIG).exists()


def test_binary_paper_assets_round_trip(setup):
    remote, seed, project = setup
    data = bytes(range(256))
    (seed / "figure.png").write_bytes(data)
    git(seed, "add", "figure.png")
    git(seed, "commit", "-m", "figure")
    git(seed, "push", "origin", "master")
    paper = imported(project)
    assert (paper / "figure.png").read_bytes() == data
    (paper / "figure.png").write_bytes(data[::-1])
    git(project, "add", "paper/figure.png")
    git(project, "commit", "-m", "edit figure")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    output = subprocess.run(
        ["git", "show", "HEAD:figure.png"], cwd=remote, check=True, capture_output=True
    ).stdout
    assert output == data[::-1]


@pytest.mark.parametrize(
    "directory",
    [
        ".",
        "../outside",
        "/tmp/outside",
        "paper/../outside",
        ".git/paper",
        ".asta/paper",
    ],
)
def test_paper_directory_cannot_escape_workspace(setup, directory):
    _, _, project = setup
    result = run(project, "pull", URL, "--dir", directory)
    assert result.exit_code == 1
    assert not (project / "paper").exists()


def test_bibliography_cache_symlink_is_rejected_before_import(setup):
    _, _, project = setup
    cache = module.cache_dir(project, URL)
    outside = project.parent / "private.txt"
    outside.write_text("private fixture")
    (cache / "overleaf-references.bib").symlink_to(outside)
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "Symlinks" in result.output
    assert outside.read_text() == "private fixture"
    assert not (project / "paper").exists()


def test_paper_file_to_directory_transition(setup):
    _, seed, project = setup
    paper = imported(project)
    git(seed, "rm", "old.tex")
    (seed / "old.tex").mkdir()
    (seed / "old.tex/nested.tex").write_text("nested\n")
    git(seed, "add", "old.tex/nested.tex")
    git(seed, "commit", "-m", "directory instead")
    git(seed, "push", "origin", "master")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (paper / "old.tex/nested.tex").read_text() == "nested\n"


def test_paper_directory_to_file_transition(setup):
    _, seed, project = setup
    (seed / "section").mkdir()
    (seed / "section/main.tex").write_text("nested\n")
    git(seed, "add", "section/main.tex")
    git(seed, "commit", "-m", "directory")
    git(seed, "push", "origin", "master")
    paper = imported(project)
    git(seed, "rm", "section/main.tex")
    (seed / "section").write_text("file now\n")
    git(seed, "add", "section")
    git(seed, "commit", "-m", "file instead")
    git(seed, "push", "origin", "master")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (paper / "section").read_text() == "file now\n"


def test_cache_must_be_ignored(setup):
    _, _, project = setup
    (project / ".gitignore").write_text("")
    git(project, "add", ".gitignore")
    git(project, "commit", "-m", "no cache ignore")
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "Ignore .asta/cache/" in result.output


def test_missing_root_bibliography_cannot_publish(setup):
    _, _, project = setup
    imported(project)
    git(project, "rm", "references.bib")
    git(project, "commit", "-m", "remove bibliography")
    result = run(project, "publish")
    assert (
        result.exit_code == 1
        and "Commit the shared root references.bib" in result.output
    )


def test_publish_reads_head_even_when_git_hides_worktree_changes(setup):
    remote, _, project = setup
    paper = imported(project)
    (paper / "main.tex").write_text("reviewed\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "reviewed change")
    git(project, "update-index", "--assume-unchanged", "paper/main.tex")
    (paper / "main.tex").write_text("unreviewed\n")
    assert git(project, "status", "--porcelain") == ""
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert git(remote, "show", "HEAD:main.tex") == "reviewed"
    assert git(remote, "show", "HEAD:references.bib") == "@misc{a}"


def test_cache_loss_requires_pull_before_republishing(setup):
    import shutil

    _, _, project = setup
    paper = imported(project)
    (paper / "main.tex").write_text("reviewed\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "reviewed change")
    assert run(project, "publish").exit_code == 0
    shutil.rmtree(project / ".asta/cache")
    result = run(project, "publish")
    assert result.exit_code == 1 and "Pull and review" in result.output
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (paper / "main.tex").read_text() == "reviewed\n"


@pytest.mark.parametrize("operation", ["publish", "pull"])
def test_stale_checkout_cannot_reuse_newer_publication_receipt(setup, operation):
    remote, _, project = setup
    paper = imported(project)
    old = git(project, "rev-parse", "HEAD")
    (paper / "main.tex").write_text("published edit\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "reviewed edit")
    assert run(project, "publish").exit_code == 0
    head = git(remote, "rev-parse", "HEAD")
    git(project, "checkout", "-q", old)
    result = run(project, operation)
    if operation == "publish":
        assert result.exit_code == 1 and "Overleaf has edits" in result.output
    else:
        assert result.exit_code == 0, result.output
        assert (paper / "main.tex").read_text() == "published edit\n"
    assert git(remote, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("recovery", ["clone", "cleared-cache"])
def test_another_clone_or_cleared_cache_requires_reviewed_pull(
    setup, tmp_path, recovery
):
    _, _, project = setup
    paper = imported(project)
    (paper / "main.tex").write_text("published edit\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "reviewed edit")
    assert run(project, "publish").exit_code == 0
    if recovery == "clone":
        clone = tmp_path / "another-clone"
        git(tmp_path, "clone", str(project), str(clone))
        project = clone
    else:
        shutil.rmtree(project / ".asta/cache")
    result = run(project, "publish")
    assert result.exit_code == 1 and "requires a fresh pull" in result.output
    assert run(project, "pull").exit_code == 0
    assert git(project, "diff", "--name-only") == "paper/overleaf.json"
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "-m", "review refreshed connection")
    result = run(project, "publish")
    assert result.exit_code == 0 and "already up to date" in result.output


def test_descendant_can_reuse_receipt_but_legacy_receipt_cannot(setup):
    remote, _, project = setup
    paper = imported(project)
    (paper / "main.tex").write_text("first edit\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "first")
    assert run(project, "publish").exit_code == 0
    receipt = module.receipt_path(project, paper, URL)
    record = json.loads(receipt.read_text())
    assert record["commit"] == git(project, "rev-parse", "HEAD")
    (paper / "main.tex").write_text("second edit\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "second")
    assert run(project, "publish").exit_code == 0
    record = json.loads(receipt.read_text())
    record.pop("commit")
    receipt.write_text(json.dumps(record))
    before = git(remote, "rev-parse", "HEAD")
    result = run(project, "publish")
    assert result.exit_code == 1 and "Overleaf has edits" in result.output
    assert git(remote, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("operation", ["pull", "publish"])
@pytest.mark.parametrize("key", ["insteadOf", "pushInsteadOf"])
def test_matching_rewrites_block_all_transport(setup, monkeypatch, operation, key):
    _, _, project = setup
    imported(project)
    cache = module.cache_dir(project, URL) / "repo.git"
    git(
        cache,
        "config",
        f"url.https://attacker.example/.{key}",
        "https://git.overleaf.com/",
    )
    transport = module.git_bytes
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")

    def no_network(*args, **kwargs):
        if any(cmd in args for cmd in ("fetch", "push")) or (
            "ls-remote" in args and "--get-url" not in args
        ):
            pytest.fail("network attempted after rewrite")
        return transport(*args, **kwargs)

    monkeypatch.setattr(module, "git_bytes", no_network)
    result = run(project, operation)
    assert result.exit_code == 1 and "URL rewrites" in result.output
    assert "fixture-token" not in result.output


def test_coauthor_bibliography_requires_explicit_reconciliation(setup):
    remote, seed, project = setup
    paper = imported(project)
    overleaf_edit(seed, "references.bib", "@misc{a}\n@misc{coauthor}\n")
    assert run(project, "pull").exit_code == 0
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "-m", "pull bibliography update")
    before = git(remote, "rev-parse", "HEAD")
    for args in [("publish",), ("publish", "--dry-run")]:
        result = run(project, *args)
        assert result.exit_code == 1 and "unreconciled entries" in result.output
        assert git(remote, "rev-parse", "HEAD") == before
    (project / "references.bib").write_text(
        "@misc{a}\n@misc{coauthor}\n@misc{workspace}\n"
    )
    result = run(project, "pull", "--reconcile-bibliography")
    assert result.exit_code == 0, result.output
    git(project, "add", "references.bib", "paper/overleaf.json")
    git(project, "commit", "-m", "review reconciliation")
    assert run(project, "publish").exit_code == 0
    assert (
        git(remote, "show", "HEAD:references.bib")
        == "@misc{a}\n@misc{coauthor}\n@misc{workspace}"
    )
    assert json.loads((paper / module.CONFIG).read_text())["bibliography_reconciled"]


def test_workspace_bibliography_can_advance_without_false_conflict(setup):
    remote, seed, project = setup
    imported(project)
    (project / "references.bib").write_text("@misc{a}\n@misc{workspace}\n")
    git(project, "add", "references.bib")
    git(project, "commit", "-m", "workspace reference")
    assert run(project, "pull").exit_code == 0
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "--allow-empty", "-m", "refresh metadata")
    assert run(project, "publish").exit_code == 0
    (project / "references.bib").write_text("@misc{a}\n@misc{workspace}\n@misc{new}\n")
    git(project, "add", "references.bib")
    git(project, "commit", "-m", "new workspace reference")
    overleaf_edit(seed, "main.tex", "coauthor prose\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    git(project, "add", "paper")
    git(project, "commit", "-m", "review prose")
    assert run(project, "publish").exit_code == 0
    assert git(remote, "show", "HEAD:references.bib").endswith("@misc{new}")


def test_cache_refs_survive_pruning_and_support_subsequent_pull(setup):
    remote, seed, project = setup
    paper = imported(project)
    base = json.loads((paper / module.CONFIG).read_text())["base"]
    (paper / "main.tex").write_text("published\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "review")
    assert run(project, "publish").exit_code == 0
    cache = module.cache_dir(project, URL) / "repo.git"
    assert git(cache, "rev-parse", "refs/overleaf/master") == base
    assert git(cache, "rev-parse", "refs/overleaf/published") == git(
        remote, "rev-parse", "HEAD"
    )
    git(cache, "gc", "--prune=now")
    overleaf_edit(seed, "old.tex", "remote\n")
    assert run(project, "pull").exit_code == 0
    assert (paper / "main.tex").read_text() == "published\n"


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"base": "a" * 40},
        {"url": 42, "base": "a" * 40},
        {"url": URL, "base": "bad"},
        {"url": URL, "base": "a" * 40, "bibliography": 42},
    ],
)
@pytest.mark.parametrize("operation", ["pull", "publish"])
def test_malformed_config_has_an_actionable_error(setup, operation, config):
    _, _, project = setup
    paper = imported(project)
    (paper / module.CONFIG).write_text(json.dumps(config))
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "-m", "invalid config")
    result = run(project, operation)
    assert result.exit_code == 1 and "Invalid overleaf.json" in result.output
    assert isinstance(result.exception, SystemExit)


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_pull_preserves_edits_hidden_from_git_status(setup, flag):
    _, seed, project = setup
    paper = imported(project)
    git(project, "update-index", flag, "paper/main.tex")
    (paper / "main.tex").write_text("hidden local edit\n")
    overleaf_edit(seed, "main.tex", "remote edit\n")
    assert git(project, "status", "--porcelain") == ""
    before = (paper / module.CONFIG).read_bytes()
    result = run(project, "pull")
    assert result.exit_code == 1 and "assume-unchanged/skip-worktree" in result.output
    assert (paper / "main.tex").read_text() == "hidden local edit\n"
    assert (paper / module.CONFIG).read_bytes() == before


def test_executable_asset_modes_survive_import_and_publication(setup):
    remote, seed, project = setup
    (seed / "build.sh").write_text("#!/bin/sh\necho paper\n")
    (seed / "build.sh").chmod(0o755)
    git(seed, "add", "build.sh")
    git(seed, "commit", "-m", "executable")
    git(seed, "push", "origin", "master")
    paper = imported(project)
    assert (paper / "build.sh").stat().st_mode & 0o111
    (paper / "main.tex").write_text("edit\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "edit")
    assert run(project, "publish").exit_code == 0
    assert git(remote, "ls-tree", "HEAD", "build.sh").startswith("100755")


def test_missing_blob_stops_pull_before_workspace_writes(setup, monkeypatch):
    _, seed, project = setup
    paper = imported(project)
    before = {p.name: p.read_bytes() for p in paper.iterdir()}
    overleaf_edit(seed, "main.tex", "first\n")
    overleaf_edit(seed, "old.tex", "second\n")
    original = module.blob
    count = 0

    def missing(repo, entry):
        nonlocal count
        count += 1
        if count == 3:
            raise module.click.ClickException("Missing object")
        return original(repo, entry)

    monkeypatch.setattr(module, "blob", missing)
    result = run(project, "pull")
    assert result.exit_code == 1 and "Missing object" in result.output
    assert {p.name: p.read_bytes() for p in paper.iterdir()} == before


def test_import_warns_about_git_control_files(setup):
    _, seed, project = setup
    overleaf_edit(seed, ".gitignore", "build/\n")
    overleaf_edit(seed, ".gitattributes", "*.tex text\n")
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    assert (
        "Review imported Git tracking/diff rules: .gitattributes, .gitignore"
        in result.output
    )


def test_uncommitted_workspace_has_clear_error(setup):
    _, _, project = setup
    git(project, "checkout", "--orphan", "empty")
    result = run(project, "pull", URL)
    assert result.exit_code == 1 and "Commit the workspace" in result.output


def test_failed_file_replacement_does_not_truncate_existing_file(tmp_path, monkeypatch):
    from pathlib import Path

    target = tmp_path / "main.tex"
    target.write_bytes(b"original")

    def fail(source, destination):
        assert destination == target
        assert target.read_bytes() == b"original"
        raise OSError("fixture disk failure")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(module.click.ClickException, match="earlier files may already"):
        module.replace_file(target, b"replacement")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("ignore_source", ["remote", "root", "exclude"])
def test_ignored_imports_cannot_be_published_as_deletions(setup, ignore_source):
    remote, seed, project = setup
    if ignore_source == "remote":
        overleaf_edit(seed, ".gitignore", "*.tex\n")
    elif ignore_source == "root":
        (project / ".gitignore").write_text(".asta/cache/\npaper/*.tex\n")
        git(project, "add", ".gitignore")
        git(project, "commit", "-m", "ignore TeX")
    else:
        (project / ".git/info/exclude").write_text("paper/*.tex\n")
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    assert "Git ignores imported files:" in result.output
    assert "paper/main.tex" in result.output and "paper/old.tex" in result.output
    git(project, "add", "paper")
    git(project, "commit", "-m", "incomplete import")
    before = git(remote, "rev-parse", "HEAD")
    for args in [("publish",), ("publish", "--dry-run")]:
        result = run(project, *args)
        assert (
            result.exit_code == 1 and "no committed workspace deletion" in result.output
        )
        assert git(remote, "rev-parse", "HEAD") == before
    # Force-add the complete import, then make an intentional deletion for review.
    git(project, "add", "-f", "paper/main.tex", "paper/old.tex")
    git(project, "commit", "-m", "complete import")
    git(project, "rm", "paper/old.tex")
    git(project, "commit", "-m", "remove unwanted source")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert git(remote, "show", "HEAD:main.tex") == "hello"
    assert "old.tex" not in git(remote, "ls-tree", "--name-only", "HEAD")


def test_deletion_before_import_does_not_authorize_omitted_remote_file(setup):
    remote, seed, project = setup
    paper = project / "paper"
    paper.mkdir()
    (paper / "old.tex").write_text("unrelated old file\n")
    git(project, "add", "paper/old.tex")
    git(project, "commit", "-m", "old paper")
    git(project, "rm", "paper/old.tex")
    git(project, "commit", "-m", "old deletion")
    overleaf_edit(seed, ".gitignore", "old.tex\n")
    imported(project)
    before = git(remote, "rev-parse", "HEAD")
    result = run(project, "publish")
    assert result.exit_code == 1 and "no committed workspace deletion" in result.output
    assert git(remote, "rev-parse", "HEAD") == before


def test_reviewed_deletion_after_publication_is_allowed(setup):
    remote, _, project = setup
    paper = imported(project)
    (paper / "main.tex").write_text("first edit\n")
    git(project, "add", "paper/main.tex")
    git(project, "commit", "-m", "edit")
    assert run(project, "publish").exit_code == 0
    git(project, "rm", "paper/old.tex")
    git(project, "commit", "-m", "reviewed deletion")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert "old.tex" not in git(remote, "ls-tree", "--name-only", "HEAD")


def test_deletion_requires_review_against_the_latest_import(setup):
    remote, seed, project = setup
    paper = imported(project)
    git(project, "rm", "paper/old.tex")
    git(project, "commit", "-m", "delete against previous import")
    overleaf_edit(seed, "new.tex", "coauthor addition\n")
    assert run(project, "pull").exit_code == 0
    git(project, "add", "paper")
    git(project, "commit", "-m", "review new import")
    before = git(remote, "rev-parse", "HEAD")
    result = run(project, "publish")
    assert result.exit_code == 1 and "no committed workspace deletion" in result.output
    assert git(remote, "rev-parse", "HEAD") == before
    (paper / "old.tex").write_text("old\n")
    git(project, "add", "paper/old.tex")
    git(project, "commit", "-m", "complete current import")
    git(project, "rm", "paper/old.tex")
    git(project, "commit", "-m", "review deletion against current import")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert "old.tex" not in git(remote, "ls-tree", "--name-only", "HEAD")
    assert git(remote, "show", "HEAD:new.tex") == "coauthor addition"


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
@pytest.mark.parametrize(
    "args", [("pull",), ("pull", "--reconcile-bibliography"), ("publish",)]
)
def test_hidden_root_bibliography_cannot_authorize_overwrite(setup, flag, args):
    remote, seed, project = setup
    paper = imported(project)
    overleaf_edit(seed, "references.bib", "@misc{a}\n@misc{coauthor}\n")
    git(project, "update-index", flag, "references.bib")
    (project / "references.bib").write_text("@misc{a}\n@misc{coauthor}\n")
    assert git(project, "status", "--porcelain") == ""
    before = (paper / module.CONFIG).read_bytes()
    head = git(remote, "rev-parse", "HEAD")
    result = run(project, *args)
    assert result.exit_code == 1 and "assume-unchanged/skip-worktree" in result.output
    assert (paper / module.CONFIG).read_bytes() == before
    assert git(remote, "rev-parse", "HEAD") == head


def test_uncommitted_root_equality_does_not_reconcile_remote_bibliography(setup):
    remote, seed, project = setup
    paper = imported(project)
    overleaf_edit(seed, "references.bib", "@misc{a}\n@misc{coauthor}\n")
    (project / "references.bib").write_text("@misc{a}\n@misc{coauthor}\n")
    result = run(project, "pull")
    assert result.exit_code == 1 and "uncommitted changes" in result.output
    git(project, "restore", "references.bib")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (
        json.loads((paper / module.CONFIG).read_text())["bibliography_reconciled"]
        is None
    )
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "-m", "metadata only")
    git(project, "restore", "references.bib")
    head = git(remote, "rev-parse", "HEAD")
    result = run(project, "publish")
    assert result.exit_code == 1 and "unreconciled entries" in result.output
    assert git(remote, "rev-parse", "HEAD") == head


def test_explicit_reconciliation_requires_the_confirmed_root_in_head(setup):
    remote, seed, project = setup
    imported(project)
    overleaf_edit(seed, "references.bib", "@misc{a}\n@misc{coauthor}\n")
    merged = "@misc{a}\n@misc{coauthor}\n@misc{workspace}\n"
    (project / "references.bib").write_text(merged)
    result = run(project, "pull", "--reconcile-bibliography")
    assert result.exit_code == 0, result.output
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "-m", "metadata only")
    git(project, "restore", "references.bib")
    # A repeat pull must not drop the binding to the confirmed root content.
    assert run(project, "pull").exit_code == 0
    assert git(project, "status", "--porcelain") == ""
    before = git(remote, "rev-parse", "HEAD")
    for args in [("publish",), ("publish", "--dry-run")]:
        result = run(project, *args)
        assert result.exit_code == 1 and "used for reconciliation" in result.output
        assert git(remote, "rev-parse", "HEAD") == before
    (project / "references.bib").write_text(merged)
    git(project, "add", "references.bib")
    git(project, "commit", "-m", "review reconciled bibliography")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert git(remote, "show", "HEAD:references.bib") == merged.strip()


def test_reimporting_missing_root_requires_committing_imported_bibliography(setup):
    remote, seed, project = setup
    imported(project)
    overleaf_edit(seed, "references.bib", "@misc{a}\n@misc{coauthor}\n")
    git(project, "rm", "references.bib")
    git(project, "commit", "-m", "remove root bibliography")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert "Imported Overleaf's bibliography" in result.output
    git(project, "add", "paper/overleaf.json")
    git(project, "commit", "-m", "metadata only")
    (project / "references.bib").write_text("@misc{a}\n")
    git(project, "add", "references.bib")
    git(project, "commit", "-m", "different root bibliography")
    before = git(remote, "rev-parse", "HEAD")
    result = run(project, "publish")
    assert result.exit_code == 1 and "used for reconciliation" in result.output
    assert git(remote, "rev-parse", "HEAD") == before


def test_reconciliation_matches_git_normalized_bibliography(setup):
    remote, seed, project = setup
    imported(project)
    (project / ".gitattributes").write_text("references.bib text eol=crlf\n")
    git(project, "add", ".gitattributes")
    git(project, "commit", "-m", "normalize bibliography line endings")
    overleaf_edit(seed, "references.bib", "@misc{a}\n@misc{coauthor}\n")
    (project / "references.bib").write_bytes(b"@misc{a}\r\n@misc{coauthor}\r\n")
    assert run(project, "pull", "--reconcile-bibliography").exit_code == 0
    git(project, "add", "paper/overleaf.json", "references.bib")
    git(project, "commit", "-m", "review reconciled bibliography")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert git(remote, "show", "HEAD:references.bib") == "@misc{a}\n@misc{coauthor}"
