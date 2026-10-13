"""Tests for `asta workspace overleaf pull|publish` against a local bare remote."""

import importlib
import json
import os
import re
import shutil
import stat
import subprocess
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from asta.cli import cli

module = importlib.import_module("asta.commands.overleaf")
CONFLICT_EXIT = module.CONFLICT_EXIT
URL = "https://git.overleaf.com/1234567"


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
    with pytest.raises(module.click.ClickException, match="git command failed"):
        module.git_bytes("--invalid-fixture-option", cwd=tmp_path)


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
    config = json.loads((paper / "overleaf.json").read_text())
    assert config == {"url": URL, "base": git(seed, "rev-parse", "HEAD")}


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
        assert json.loads((paper / "overleaf.json").read_text())["base"] == git(
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
    before = (project / "paper/overleaf.json").read_bytes()
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
    assert (project / "paper/overleaf.json").read_bytes() == before
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
    before = (project / "paper/overleaf.json").read_bytes()
    remote_before = git(seed, "rev-parse", "origin/master")
    hook = project / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o700)
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert (result.exit_code == 0) == dry_run, result.output
    if not dry_run:
        assert "commit hooks and signing settings" in result.output
        assert "not the full workspace" in result.output
    assert (project / "paper/overleaf.json").read_bytes() == before
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
    before = (project / "paper/overleaf.json").read_bytes()
    overleaf_edit(seed, "main.tex", remote_text)
    result = run(project, "pull")
    if remote_text is None:
        assert result.exit_code != 0 and "disagree on whether main.tex" in result.output
        assert (project / "paper/main.tex").read_text() == "reviewed workspace edit\n"
        assert (project / "paper/overleaf.json").read_bytes() == before
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
    assert "Both workspace and Overleaf changed main.tex" in result.output
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
    metadata = (project / "paper/overleaf.json").read_bytes()
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
    assert (project / "paper/overleaf.json").read_bytes() == metadata
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
    before = (project / "paper/overleaf.json").read_bytes()
    overleaf_edit(seed, "old.tex", None)
    overleaf_edit(seed, "figure.png", "remote figure\n")
    result = run(project, "pull")
    assert result.exit_code != 0 and "paper/figure.png is ignored" in result.output
    assert "Adjust the ignore rules" in result.output
    assert not (project / "paper/figure.png").exists()
    assert (project / "paper/old.tex").read_text() == "old\n"
    assert (project / "paper/overleaf.json").read_bytes() == before
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("pattern", ["/paper/", "/paper/overleaf.json"])
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


@pytest.mark.parametrize("name", ["overleaf.json", ".gitignore", "nested/.gitignore"])
def test_pull_refuses_remote_metadata_and_ignore_rules_before_writing(setup, name):
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
    "name", ["Overleaf.json", "overleaf.jſon", "Overleaf.json/content.tex"]
)
@pytest.mark.parametrize("existing_paper", [False, True])
def test_pull_refuses_sync_record_aliases_before_writing(setup, name, existing_paper):
    seed, project = setup
    paper = project / "paper"
    if existing_paper:
        assert run(project, "pull", URL).exit_code == 0
        commit_all(project)
    before = {
        str(path.relative_to(paper)): path.read_bytes()
        for path in paper.rglob("*")
        if path.is_file()
    }
    (seed / name).parent.mkdir(parents=True, exist_ok=True)
    overleaf_edit(seed, name, "valuable remote content\n")
    remote_head = git(seed, "ls-remote", "origin", "master")

    result = run(project, "pull", URL)

    assert result.exit_code != 0
    assert "only in letter case or Unicode normalization" in result.output
    assert "overleaf.json" in result.output
    assert {
        str(path.relative_to(paper)): path.read_bytes()
        for path in paper.rglob("*")
        if path.is_file()
    } == before
    assert paper.exists() == existing_paper
    assert git(seed, "ls-remote", "origin", "master") == remote_head


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
    record = (project / "paper/overleaf.json").read_bytes()
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert (project / "paper/overleaf.json").read_bytes() == record
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
@pytest.mark.parametrize("command", ["pull", "publish"])
@pytest.mark.parametrize("replay", ["older", "cherry-pick", "after-recorded-pull"])
def test_replayed_publication_requires_pull_and_review(setup, command, replay):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("first published paper\n")
    commit_all(project)
    first_source = git(project, "rev-parse", "HEAD")
    assert run(project, "publish").exit_code == 0
    git(seed, "pull", "-q", "origin", "master")
    first_publish = git(seed, "rev-parse", "HEAD")
    (project / "paper/main.tex").write_text("latest published paper\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    if replay == "cherry-pick":
        overleaf_edit(seed, "main.tex", "collaborator paper\n")
        git(seed, "cherry-pick", "--strategy=recursive", "-X", "theirs", first_publish)
    else:
        git(seed, "pull", "-q", "origin", "master")
        if replay == "after-recorded-pull":
            assert run(project, "pull").exit_code == 0
            commit_all(project)
            git(project, "push", "-q", "origin", "HEAD:main")
        (seed / "main.tex").write_text("first published paper\n")
        git(seed, "add", "main.tex")
        git(seed, "commit", "-q", "-m", f"Publish workspace commit {first_source}")
    git(seed, "push", "-q", "origin", "master")
    before_remote = git(seed, "ls-remote", "origin", "master")
    before_record = (project / "paper/overleaf.json").read_bytes()

    result = run(project, command, merge=False)

    assert git(seed, "ls-remote", "origin", "master") == before_remote
    if command == "publish":
        assert result.exit_code == 1 and "Overleaf has changed" in result.output
        assert (project / "paper/overleaf.json").read_bytes() == before_record
        assert not git(project, "status", "--porcelain")
    else:
        assert result.exit_code == 0, result.output
        assert (project / "paper/main.tex").read_text() == "first published paper\n"
        assert git(project, "diff", "--", "paper/main.tex")
        commit_all(project)
        assert run(project, "publish").exit_code == 0


@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_ordinary_head_does_not_complete_old_publication_history(
    setup, dry_run
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("published paper\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    (project / "outside.txt").write_text("later reviewed workspace commit\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    shallow = project.parent / "shallow"
    git(
        project.parent,
        "clone",
        "--depth=1",
        (project.parent / "workspace.git").as_uri(),
        str(shallow),
    )
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    shallow_file = shallow / git(shallow, "rev-parse", "--git-path", "shallow")
    before_shallow = shallow_file.read_bytes()
    before_refs = git(shallow, "show-ref")
    fetch_head = shallow / git(shallow, "rev-parse", "--git-path", "FETCH_HEAD")
    before_fetch = fetch_head.read_bytes() if fetch_head.exists() else None
    before_remote = git(seed, "ls-remote", "origin", "master")
    result = run(shallow, "publish", *(["--dry-run"] if dry_run else []), merge=False)
    assert result.exit_code == 1 and "Overleaf has changed" in result.output
    assert "shallow history" not in result.output
    assert shallow_file.read_bytes() == before_shallow
    assert git(shallow, "show-ref") == before_refs
    assert (fetch_head.read_bytes() if fetch_head.exists() else None) == before_fetch
    assert git(seed, "ls-remote", "origin", "master") == before_remote
    assert not git(shallow, "status", "--porcelain")


@pytest.mark.parametrize("missing", ["stale-clone", "pruned"])
@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_pull_fetches_publication_source_from_reviewed_history(setup, missing):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed paper\n")
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
    publisher = project.parent / "publisher"
    git(
        project.parent,
        "clone",
        git(project, "remote", "get-url", "origin"),
        str(publisher),
    )
    (publisher / "outside.txt").write_text("later reviewed non-paper change\n")
    commit_all(publisher)
    git(publisher, "push", "-q", "origin", "HEAD:main")
    source = git(publisher, "rev-parse", "HEAD")
    assert run(project, "publish", merge=False).exit_code == 0
    if missing == "pruned":
        git(project, "reflog", "expire", "--expire=now", "--all")
        git(project, "gc", "--prune=now")
        target = project
    else:
        target = stale
    assert (
        subprocess.run(
            ["git", "cat-file", "-e", source], cwd=target, capture_output=True
        ).returncode
        != 0
    )
    before_refs = git(target, "show-ref")
    fetch_head = target / git(target, "rev-parse", "--git-path", "FETCH_HEAD")
    before_fetch = fetch_head.read_bytes() if fetch_head.exists() else None
    overleaf_edit(seed, "main.tex", "collaborator edit\n")

    result = run(target, "pull")

    assert result.exit_code == 0, result.output
    assert "same lines" not in result.output
    assert (target / "paper/main.tex").read_text() == "collaborator edit\n"
    assert git(target, "show-ref") == before_refs
    assert (fetch_head.read_bytes() if fetch_head.exists() else None) == before_fetch


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
        json.loads((stale / "paper/overleaf.json").read_text())["base"] == remote_head
    )
    assert git(stale, "diff", "--", "paper/main.tex")
    assert git(stale, "show-ref") == before_refs


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_pull_skips_unseen_publication_and_uses_previous_local_publication(setup):
    seed, project = setup
    overleaf_edit(seed, "main.tex", "one\ntwo\nthree\nfour\n")
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("ONE\ntwo\nthree\nfour\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    first = git(project, "rev-parse", "HEAD")
    (project / "paper/main.tex").write_text("ONE\ntwo\nthree\nFOUR\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    git(project, "switch", "-q", "-c", "older-checkout", first)
    (project / "paper/main.tex").write_text("ONE\nTWO\nthree\nfour\n")
    commit_all(project)

    result = run(project, "pull")

    assert result.exit_code == 0, result.output
    assert "same lines" not in result.output
    assert (project / "paper/main.tex").read_text() == "ONE\nTWO\nthree\nFOUR\n"


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


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("source_present", [False, True])
def test_shallow_clone_recognizes_older_reviewed_publication(setup, source_present):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("one\ntwo\nthree\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    source = git(project, "rev-parse", "HEAD")
    (project / "paper/main.tex").write_text("ONE\ntwo\nthree\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    shallow = project.parent / "shallow"
    origin = (project.parent / "workspace.git").as_uri()
    git(project.parent, "clone", "--depth=1", origin, str(shallow))
    if source_present:
        git(shallow, "fetch", "--depth=1", "origin", source)
        git(shallow, "cat-file", "-e", source)
        assert (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", source, "HEAD"],
                cwd=shallow,
                capture_output=True,
            ).returncode
            == 1
        )
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "true"
    before_refs = git(shallow, "show-ref")
    fetch_head = shallow / git(shallow, "rev-parse", "--git-path", "FETCH_HEAD")
    before_fetch = fetch_head.read_bytes() if fetch_head.exists() else None
    overleaf_edit(seed, "main.tex", "one\ntwo\nTHREE\n")

    result = run(shallow, "pull")

    assert result.exit_code == 0, result.output
    assert "same lines" not in result.output
    assert (shallow / "paper/main.tex").read_text() == "ONE\ntwo\nTHREE\n"
    assert git(shallow, "show-ref") == before_refs
    assert (fetch_head.read_bytes() if fetch_head.exists() else None) == before_fetch
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "false"


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
def test_unrecognized_bridge_history_requires_pull_and_review(setup, rewrite):
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
    before_record = (project / "paper/overleaf.json").read_bytes()

    result = run(project, "publish")

    assert result.exit_code == 1 and "Overleaf has changed" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before_remote
    assert (project / "paper/overleaf.json").read_bytes() == before_record
    assert not git(project, "status", "--porcelain")
    pulled = run(project, "pull")
    assert pulled.exit_code == 0, pulled.output
    assert (project / "paper/main.tex").read_text() == "reviewed publication\n"
    assert git(project, "diff", "--name-only") == "paper/overleaf.json"
    assert json.loads((project / "paper/overleaf.json").read_text())["base"] == git(
        seed, "rev-parse", "HEAD"
    )


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("source_present", [False, True])
def test_dry_run_does_not_complete_older_publication_history(setup, source_present):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    source = git(project, "rev-parse", "HEAD")
    (project / "paper/main.tex").write_text("next reviewed publication\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    shallow = project.parent / "shallow"
    git(
        project.parent,
        "clone",
        "--depth=1",
        (project.parent / "workspace.git").as_uri(),
        str(shallow),
    )
    if source_present:
        git(shallow, "fetch", "--depth=1", "origin", source)
    shallow_file = shallow / git(shallow, "rev-parse", "--git-path", "shallow")
    fetch_head = shallow / git(shallow, "rev-parse", "--git-path", "FETCH_HEAD")
    before_shallow = shallow_file.read_bytes()
    before_fetch = fetch_head.read_bytes() if fetch_head.exists() else None
    before_refs = git(shallow, "show-ref")
    before_remote = git(seed, "ls-remote", "origin", "master")
    before_record = (shallow / "paper/overleaf.json").read_bytes()

    result = run(shallow, "publish", "--dry-run", merge=False)

    assert result.exit_code == 1, result.output
    assert "shallow history" in result.output and "dry-run" in result.output
    assert "nothing pushed" in result.output.lower()
    assert "Overleaf has changed" not in result.output
    assert shallow_file.read_bytes() == before_shallow
    assert (fetch_head.read_bytes() if fetch_head.exists() else None) == before_fetch
    assert git(shallow, "show-ref") == before_refs
    assert git(seed, "ls-remote", "origin", "master") == before_remote
    assert (shallow / "paper/overleaf.json").read_bytes() == before_record
    assert not git(shallow, "status", "--porcelain")
    published = run(shallow, "publish", merge=False)
    assert published.exit_code == 0, published.output
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "false"
    assert "Fetching complete workspace history" in published.output


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("command", ["pull", "publish"])
@pytest.mark.parametrize("source_present", [False, True])
def test_history_fetch_failure_has_command_specific_diagnostics(
    setup, monkeypatch, command, source_present
):
    seed, project = setup
    overleaf_edit(seed, "main.tex", "one\ntwo\nthree\n")
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("ONE\ntwo\nthree\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    source = git(project, "rev-parse", "HEAD")
    (project / "outside.txt").write_text("later reviewed workspace edit\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    shallow = project.parent / "shallow"
    git(
        project.parent,
        "clone",
        "--depth=1",
        (project.parent / "workspace.git").as_uri(),
        str(shallow),
    )
    if source_present:
        git(shallow, "fetch", "--depth=1", "origin", source)
    if command == "pull":
        overleaf_edit(seed, "main.tex", "ONE\ntwo\nTHREE\n")
    before_remote = git(seed, "ls-remote", "origin", "master")
    before_record = (shallow / "paper/overleaf.json").read_bytes()
    real_run = module.subprocess.run

    def fail_fetch(args, **kwargs):
        if args[0] == "git" and "fetch" in args and "--unshallow" in args:
            return subprocess.CompletedProcess(
                args, 128, b"", b"authentication failed: fixture-secret"
            )
        return real_run(args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", fail_fetch)
    result = run(shallow, command, merge=False)

    assert "fixture-secret" not in result.output
    assert git(seed, "ls-remote", "origin", "master") == before_remote
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "true"
    if command == "publish":
        assert result.exit_code == 1
        assert (
            "Could not fetch complete" in result.output
            and "credentials" in result.output
        )
        assert "nothing pushed" in result.output.lower()
        assert "Overleaf has changed" not in result.output
        assert (shallow / "paper/overleaf.json").read_bytes() == before_record
        assert not git(shallow, "status", "--porcelain")
    else:
        assert result.exit_code == 0, result.output
        assert "Pulling from the recorded sync" in result.output
        assert (shallow / "paper/main.tex").read_text() == "ONE\ntwo\nTHREE\n"
        assert (
            json.loads((shallow / "paper/overleaf.json").read_text())["base"]
            == before_remote.split()[0]
        )


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("branch", ["main", "papers/reviewed"])
def test_history_completion_uses_advertised_ref_after_default_branch_advances(
    setup, monkeypatch, branch
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed publication\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    (project / "paper/main.tex").write_text("next reviewed publication\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    reviewed = git(project, "rev-parse", "HEAD")
    if branch != "main":
        git(project, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        git(
            project.parent / "workspace.git",
            "symbolic-ref",
            "HEAD",
            f"refs/heads/{branch}",
        )
    shallow = project.parent / "shallow"
    git(
        project.parent,
        "clone",
        "--depth=1",
        (project.parent / "workspace.git").as_uri(),
        str(shallow),
    )
    before_refs = git(shallow, "show-ref")
    fetch_head = shallow / git(shallow, "rev-parse", "--git-path", "FETCH_HEAD")
    git(shallow, "fetch", "--depth=1", "origin", f"refs/heads/{branch}")
    before_fetch = fetch_head.read_bytes()
    real_run = module.subprocess.run
    attempts = []

    def advertised_only(args, **kwargs):
        if args[0] == "git" and "fetch" in args and "--unshallow" in args:
            attempts.append(args[-1])
            (project / "paper/main.tex").write_text(
                "reviewed after the gate was fetched\n"
            )
            commit_all(project)
            git(project, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
            # Model a server that accepts advertised refs but refuses ancestor OID wants.
            if not args[-1].startswith("refs/heads/"):
                return subprocess.CompletedProcess(
                    args, 128, b"", b"unadvertised object fixture-secret"
                )
        return real_run(args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", advertised_only)
    result = run(shallow, "publish", merge=False)

    assert result.exit_code == 0, result.output
    assert attempts == [f"refs/heads/{branch}"]
    assert "fixture-secret" not in result.output
    assert git(shallow, "show-ref") == before_refs
    assert fetch_head.read_bytes() == before_fetch
    assert not git(shallow, "status", "--porcelain")
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "next reviewed publication\n"
    assert (
        git(seed, "log", "-1", "--format=%s") == f"Publish workspace commit {reviewed}"
    )


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_history_completion_does_not_accept_newly_reviewed_publication(
    setup, monkeypatch
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed paper\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    reviewed = git(project, "rev-parse", "HEAD")
    shallow = project.parent / "shallow"
    git(
        project.parent,
        "clone",
        "--depth=1",
        (project.parent / "workspace.git").as_uri(),
        str(shallow),
    )
    (project / "outside.txt").write_text("revision not yet merged at the gate\n")
    commit_all(project)
    future = git(project, "rev-parse", "HEAD")
    (seed / "main.tex").write_text("reviewed paper\n")
    git(seed, "add", "main.tex")
    git(seed, "commit", "-q", "-m", f"Publish workspace commit {future}")
    git(seed, "push", "-q", "origin", "master")
    before_remote = git(seed, "ls-remote", "origin", "master")
    before_record = (shallow / "paper/overleaf.json").read_bytes()
    real_run = module.subprocess.run
    attempts = []

    def advance_branch(args, **kwargs):
        if args[0] == "git" and "fetch" in args and "--unshallow" in args:
            attempts.append(args[-1])
            git(project, "push", "-q", "origin", "HEAD:main")
        return real_run(args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", advance_branch)
    result = run(shallow, "publish", merge=False)

    assert len(attempts) == 1
    assert result.exit_code == 1 and "Overleaf has changed" in result.output
    assert git(shallow, "rev-parse", "HEAD") == reviewed
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "false"
    assert (shallow / "paper/overleaf.json").read_bytes() == before_record
    assert git(seed, "ls-remote", "origin", "master") == before_remote
    assert not git(shallow, "status", "--porcelain")


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("unavailable", ["missing", "renamed", "offline"])
@pytest.mark.parametrize("conflict", [False, True])
def test_pull_falls_back_to_recorded_sync_without_origin(setup, unavailable, conflict):
    seed, project = setup
    overleaf_edit(seed, "main.tex", "one\ntwo\nthree\n")
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("ONE\ntwo\nthree\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    overleaf_edit(
        seed, "main.tex", "remote\ntwo\nthree\n" if conflict else "ONE\ntwo\nTHREE\n"
    )
    if unavailable == "missing":
        git(project, "remote", "remove", "origin")
    elif unavailable == "renamed":
        git(project, "remote", "rename", "origin", "upstream")
    else:
        git(project, "remote", "set-url", "origin", str(project.parent / "offline.git"))

    result = run(project, "pull")

    assert result.exit_code == (CONFLICT_EXIT if conflict else 0), result.output
    assert "Pulling from the recorded sync" in result.output
    assert "offline.git" not in result.output
    content = (project / "paper/main.tex").read_text()
    if conflict:
        assert "<<<<<<< workspace\nONE\n" in content
        assert "remote\n>>>>>>> overleaf\n" in content
    else:
        assert content == "ONE\ntwo\nTHREE\n"
    assert json.loads((project / "paper/overleaf.json").read_text())["base"] == git(
        seed, "rev-parse", "HEAD"
    )
    if not conflict:
        commit_all(project)
        before = git(seed, "ls-remote", "origin", "master")
        publish = run(project, "publish", merge=False)
        assert publish.exit_code == 1 and "`origin` remote" in publish.output
        assert git(seed, "ls-remote", "origin", "master") == before


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize("command", ["pull", "publish", "dry-run"])
def test_sync_keeps_shallow_history_when_publication_is_at_tip(
    setup, published, command
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
        "--depth=1",
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

    assert result.exit_code == 0, result.output
    assert shallow_file.read_bytes() == before_shallow
    assert git(shallow, "show-ref") == before_refs
    assert (fetch_head.read_bytes() if fetch_head.exists() else None) == before_fetch
    assert git(shallow, "diff", "--name-only") == (
        "paper/overleaf.json" if command == "pull" and published else ""
    )
    assert git(shallow, "status", "--porcelain") == (
        "M paper/overleaf.json" if command == "pull" and published else ""
    )


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
    assert "Reset remote history is unsupported" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert not git(project, "status", "--porcelain")


def test_bibliography_refuses_edit_deleted_on_overleaf(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/references.bib").write_text("@misc{workspace_edit}\n")
    commit_all(project)
    before = (project / "paper/overleaf.json").read_bytes()
    overleaf_edit(seed, "references.bib", None)
    result = run(project, "pull")
    assert result.exit_code != 0
    assert "disagree on whether references.bib exists" in result.output
    assert (project / "paper/references.bib").read_text() == "@misc{workspace_edit}\n"
    assert (project / "paper/overleaf.json").read_bytes() == before


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
    record = (project / "paper/overleaf.json").read_bytes()
    result = run(project, "publish")
    assert result.exit_code != 0 and ".gitignore" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / "paper/overleaf.json").read_bytes() == record


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
    record = (paper / "overleaf.json").read_bytes()
    git(seed, "rm", "-r", "-q", "nested")
    (seed / "nested").write_text("now a file\n")
    commit_all(seed)
    git(seed, "push", "-q", "origin", "master")
    result = run(project, "pull")
    assert result.exit_code != 0 and "Move the directory aside" in result.output
    assert (paper / "nested/figure.tex").read_text() == "figure\n"
    assert (paper / "overleaf.json").read_bytes() == record


def test_pull_empty_remote_commit(setup):
    seed, project = setup
    git(seed, "rm", "-r", ".")
    commit_all(seed)
    git(seed, "push", "-q", "origin", "master")
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    assert json.loads((project / "paper/overleaf.json").read_text())["base"] == git(
        seed, "rev-parse", "HEAD"
    )


@pytest.mark.parametrize(
    "text",
    ["{", "[]", "null", '"value"', "{}", '{"url": 42, "base": "' + "a" * 40 + '"}'],
)
@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_reports_invalid_metadata(setup, text, command, monkeypatch):
    _, project = setup
    paper = project / "paper"
    paper.mkdir()
    (paper / "overleaf.json").write_text(text)
    commit_all(project)
    monkeypatch.setattr(module, "clone", lambda *a: pytest.fail("must not clone"))
    result = run(project, command)
    assert result.exit_code == 1
    assert (
        "Invalid sync record" in result.output
        and "paper/overleaf.json" in result.output
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
    git(project, "rm", "--cached", "paper/overleaf.json")
    (project / ".gitignore").write_text("paper/overleaf.json\n")
    commit_all(project)
    overleaf_edit(seed, "main.tex", "newer Overleaf content\n")
    path = project / "paper/overleaf.json"
    record = json.loads(path.read_text())
    record["base"] = git(seed, "rev-parse", "HEAD")
    path.write_text(json.dumps(record))
    before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish")
    assert result.exit_code != 0 and "overleaf.json is ignored" in result.output
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
    record = (project / "paper/overleaf.json").read_bytes()
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert (
        result.exit_code != 0
        and "Configure Git user.name and user.email" in result.output
    )
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / "paper/overleaf.json").read_bytes() == record


def test_pull_reports_unavailable_base_before_modifying_sources(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    path = project / "paper/overleaf.json"
    config = json.loads(path.read_text())
    config["base"] = "0" * 40
    path.write_text(json.dumps(config))
    commit_all(project)
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    result = run(project, "pull")
    assert (
        result.exit_code != 0 and "Reset remote history is unsupported" in result.output
    )
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before


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
    assert "Reset remote history is unsupported" in result.output
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
    git(project, "update-index", "--assume-unchanged", "paper/overleaf.json")
    record = project / "paper/overleaf.json"
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
    record = (project / "paper/overleaf.json").read_bytes()
    before = git(seed, "ls-remote", "origin", "master")
    monkeypatch.setattr(
        module, "clone", lambda *args: pytest.fail("must refuse before transport")
    )
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert result.exit_code != 0 and "local changes" in result.output
    assert "paper/main.tex" in result.output
    assert git(seed, "ls-remote", "origin", "master") == before
    assert (project / "paper/overleaf.json").read_bytes() == record
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
    record = (project / "paper/overleaf.json").read_bytes()
    overleaf_edit(seed, "main.tex", remote_edit)
    result = run(project, "pull")
    assert result.exit_code != 0 and "local changes" in result.output
    assert source.read_text() == "uncommitted local edits\n"
    assert (project / "paper/overleaf.json").read_bytes() == record
    assert (project / "paper/old.tex").read_text() == "old\n"


def test_pull_preserves_sync_record_hidden_by_index_flags(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "update-index", "--assume-unchanged", "paper/overleaf.json")
    record = project / "paper/overleaf.json"
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
    assert json.loads((project / "paper/overleaf.json").read_text())["base"] == git(
        seed, "rev-parse", "HEAD"
    )


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
    before = (project / "paper/overleaf.json").read_bytes()
    remote_before = git(seed, "ls-remote", "origin", "master")
    result = run(project, "publish", *(["--dry-run"] if dry_run else []))
    assert result.exit_code != 0 and "empty paper" in result.output
    assert (project / "paper/overleaf.json").read_bytes() == before
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
    git(project, "add", "--", "paper/main.tex", "paper/overleaf.json")
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
    git(project, "add", "--", "paper/figure.pdf", "paper/overleaf.json")
    git(project, "commit", "-q", "-m", "include reviewed figure")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "figure.pdf").read_bytes() == asset.read_bytes()
    assert not git(project, "status", "--porcelain")
    before_record = (paper / "overleaf.json").read_bytes()
    before_remote = git(seed, "rev-parse", "HEAD")
    asset.write_bytes(b"unreviewed figure change\n")
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "local changes" in result.output
    assert git(seed, "ls-remote", "origin", "master").split()[0] == before_remote
    assert (paper / "overleaf.json").read_bytes() == before_record
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
    git(project, "add", "--", "paper/overleaf.json", f"paper/{name}")
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
    before_record = (project / "paper/overleaf.json").read_bytes()
    before_remote = git(seed, "ls-remote", "origin", "master")
    hook = project / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\ntest -f .pre-commit-config.yaml\n")
    hook.chmod(0o700)
    result = run(project, "publish")
    assert result.exit_code != 0
    assert "commit hooks and signing settings" in result.output
    assert "exported paper directory, not the full workspace" in result.output
    assert (project / "paper/overleaf.json").read_bytes() == before_record
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


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_history_completion_keeps_gate_branch_when_origin_head_changes(
    setup, monkeypatch, command
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("published paper\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    (project / "outside.txt").write_text("later reviewed workspace commit\n")
    commit_all(project)
    git(project, "push", "-q", "origin", "HEAD:main")
    shallow = project.parent / "shallow"
    git(
        project.parent,
        "clone",
        "--depth=1",
        (project.parent / "workspace.git").as_uri(),
        str(shallow),
    )
    origin = project.parent / "workspace.git"
    git(
        origin,
        "update-ref",
        "refs/heads/replacement",
        git(origin, "rev-list", "--max-parents=0", "main"),
    )
    real_run = module.subprocess.run
    discoveries, completions = [], []

    def switch_default(args, **kwargs):
        if args[0] == "git" and "ls-remote" in args and "--symref" in args:
            discoveries.append(args)
        if (
            args[0] == "git"
            and "fetch" in args
            and any("overleaf-gate" in str(arg) for arg in args)
        ):
            result = real_run(args, **kwargs)
            git(origin, "symbolic-ref", "HEAD", "refs/heads/replacement")
            return result
        if args[0] == "git" and "fetch" in args and "--unshallow" in args:
            completions.append(args[-1])
        return real_run(args, **kwargs)

    if command == "pull":
        overleaf_edit(seed, "main.tex", "collaborator edit\n")
    monkeypatch.setattr(module.subprocess, "run", switch_default)
    result = run(shallow, command, merge=False)
    assert result.exit_code == 0, result.output
    assert len(discoveries) == 1
    assert completions == ["refs/heads/main"]
    assert "Fetching complete workspace history" in result.output
    if command == "pull":
        assert (shallow / "paper/main.tex").read_text() == "collaborator edit\n"
