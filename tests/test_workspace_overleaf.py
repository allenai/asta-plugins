"""Tests for `asta workspace overleaf pull|publish` against a local bare remote."""

import importlib
import json
import os
import subprocess
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from asta.cli import cli

module = importlib.import_module("asta.commands.overleaf")
URL = "https://git.overleaf.com/1234567"


def test_git_environment_removes_all_repository_overrides(tmp_path, monkeypatch):
    local_names = git(tmp_path, "rev-parse", "--local-env-vars").splitlines()
    for name in [*local_names, "GIT_NAMESPACE"]:
        monkeypatch.setenv(name, "fixture-override")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "personal-config")
    env = module.git_environment()
    assert not set([*local_names, "GIT_NAMESPACE"]) & env.keys()
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
    ],
)
def test_transport_auth_errors_are_actionable(
    tmp_path, monkeypatch, diagnostic, reason
):
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: subprocess.CompletedProcess(a[0], 128, b"", diagnostic)
        ),
    )
    with pytest.raises(module.click.ClickException, match=reason):
        module.git_bytes("clone", cwd=tmp_path)


def test_windows_token_failure_recommends_credential_helper(monkeypatch):
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt", environ=os.environ))
    with pytest.raises(module.click.ClickException, match="credential helper"):
        with module.credentials():
            pytest.fail("must refuse shell askpass on Windows")


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_reports_unborn_workspace_head(tmp_path, command):
    git(tmp_path, "init", "-b", "main")
    result = run(tmp_path, command, *([URL] if command == "pull" else []))
    assert result.exit_code != 0
    assert "Commit the workspace's initial files" in result.output


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


@pytest.mark.parametrize("command", ["pull", "publish"])
@pytest.mark.parametrize("attribute", ["text=auto", "eol=crlf", "filter=lfs", "crlf"])
@pytest.mark.parametrize("location", ["root", "info", "global"])
def test_sync_refuses_workspace_attributes_before_changes(
    setup, monkeypatch, command, attribute, location
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    if command == "pull":
        overleaf_edit(seed, "old.tex", None)
    before = {p.name: p.read_bytes() for p in (project / "paper").iterdir()}
    remote_before = git(seed, "ls-remote", "origin", "master")
    if location == "root":
        attributes = project / ".gitattributes"
    elif location == "info":
        attributes = project / ".git/info/attributes"
    else:
        attributes = project.parent / "global-attributes"
        git(project, "config", "core.attributesFile", str(attributes))
    attributes.write_text(f"paper/* {attribute}\n")
    result = run(project, command)
    assert result.exit_code != 0 and "content-changing Git attribute" in result.output
    assert {p.name: p.read_bytes() for p in (project / "paper").iterdir()} == before
    assert git(seed, "ls-remote", "origin", "master") == remote_before


def test_pull_preserves_crlf_when_attributes_explicitly_disabled(setup):
    seed, project = setup
    (seed / "main.tex").write_bytes(b"hello\r\n")
    commit_all(seed)
    git(seed, "push", "origin", "master")
    (project / ".gitattributes").write_text("paper/* -text -filter -crlf\n")
    commit_all(project)
    result = run(project, "pull", URL)
    assert result.exit_code == 0, result.output
    commit_all(project)
    assert module.git_bytes("show", "HEAD:paper/main.tex", cwd=project) == b"hello\r\n"


@pytest.mark.parametrize("command", ["pull", "publish"])
def test_sync_checks_committed_ancestor_attributes(setup, command):
    _, project = setup
    (project / "papers").mkdir()
    assert run(project, "pull", URL, "--dir", "papers/article").exit_code == 0
    (project / "papers/.gitattributes").write_text("article/* text=auto\n")
    commit_all(project)
    # A working-tree edit must not hide transformations in the committed rules.
    (project / "papers/.gitattributes").write_text("article/* -text\n")
    result = run(project, command, "--dir", "papers/article")
    assert result.exit_code != 0 and "content-changing Git attribute" in result.output


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


def test_pull_write_error_is_actionable(setup, monkeypatch):
    _, project = setup
    monkeypatch.setattr(
        module, "write_files", lambda *a: (_ for _ in ()).throw(PermissionError())
    )
    result = run(project, "pull", URL)
    assert (
        result.exit_code != 0
        and "Check permissions and free disk space" in result.output
    )
    assert "git diff" in result.output
    assert not (project / "paper/overleaf.json").exists()


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
    assert "OVERLEAF_TOKEN" not in module.git_environment()
    with module.credentials() as (env, options):
        askpass = env["GIT_ASKPASS"]
        assert options == ["-c", "credential.helper="]
        answer = subprocess.run(
            [askpass, "Password for x"], env=env, capture_output=True, text=True
        )
        assert answer.stdout.strip() == "fixture-token"
        assert "fixture-token" not in open(askpass).read()
    assert not os.path.exists(askpass)


@pytest.mark.skipif(os.name == "nt", reason="POSIX commit hook and askpass")
def test_publish_keeps_token_out_of_commit_hooks(setup, tmp_path, monkeypatch):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/main.tex").write_text("reviewed edit\n")
    commit_all(project)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        'test -z "$OVERLEAF_TOKEN" || exit 1\n'
        'printf checked > "$TEST_HOOK_MARKER"\n'
    )
    hook.chmod(0o700)
    config = tmp_path / "gitconfig"
    config.write_text(f"[core]\n\thooksPath = {hooks}\n")
    marker = tmp_path / "hook-ran"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("TEST_HOOK_MARKER", str(marker))
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    assert marker.read_text() == "checked"
    git(seed, "pull", "-q", "origin", "master")
    assert (seed / "main.tex").read_text() == "reviewed edit\n"


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


@pytest.mark.parametrize("remote_text", ["@misc{collaborator}\n", None])
def test_bibliography_uses_same_conflict_protection_as_other_sources(
    setup, remote_text
):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    (project / "paper/references.bib").write_text("@misc{workspace_edit}\n")
    commit_all(project)
    before = (project / "paper/overleaf.json").read_bytes()
    overleaf_edit(seed, "references.bib", remote_text)
    result = run(project, "pull")
    assert (
        result.exit_code != 0
        and "Both workspace and Overleaf changed references.bib" in result.output
    )
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
    commit_all(project)
    overleaf_edit(seed, "main.tex", "collaborator follow-up\n")
    result = run(project, "pull")
    assert result.exit_code == 0, result.output
    assert (project / "paper/main.tex").read_text() == "collaborator follow-up\n"


@pytest.mark.parametrize("ignored_file", [False, True])
def test_pull_directory_to_file_replacement(setup, ignored_file):
    seed, project = setup
    (seed / "nested/deep").mkdir(parents=True)
    overleaf_edit(seed, "nested/deep/figure.tex", "figure\n")
    assert run(project, "pull", URL).exit_code == 0
    (project / ".gitignore").write_text("*.aux\n")
    commit_all(project)
    paper = project / "paper"
    record = (paper / "overleaf.json").read_bytes()
    if ignored_file:
        (paper / "nested/local.aux").write_text("keep local\n")
    git(seed, "rm", "-r", "nested")
    (seed / "nested").write_text("now a file\n")
    commit_all(seed)
    git(seed, "push", "-q", "origin", "master")
    result = run(project, "pull")
    if ignored_file:
        assert result.exit_code != 0 and "directory" in result.output.lower()
        assert (paper / "nested/local.aux").read_text() == "keep local\n"
        assert (paper / "nested/deep/figure.tex").read_text() == "figure\n"
        assert (paper / "overleaf.json").read_bytes() == record
    else:
        assert result.exit_code == 0, result.output
        assert (paper / "nested").read_text() == "now a file\n"
        commit_all(project)
        git(seed, "rm", "nested")
        (seed / "nested").mkdir()
        overleaf_edit(seed, "nested/figure.tex", "back to a directory\n")
        result = run(project, "pull")
        assert result.exit_code == 0, result.output
        assert (paper / "nested/figure.tex").read_text() == "back to a directory\n"


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
    assert str(error.value) == f"git {operation} failed (exit 1)."


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


def test_pull_refuses_replacement_directory_with_untracked_former_remote_file(setup):
    seed, project = setup
    (seed / "nested").mkdir()
    overleaf_edit(seed, "nested/draft.tex", "remote draft\n")
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "rm", "--cached", "paper/nested/draft.tex")
    (project / ".gitignore").write_text("/paper/nested/draft.tex\n")
    commit_all(project)
    draft = project / "paper/nested/draft.tex"
    draft.write_text("local ignored draft\n")
    record = (project / "paper/overleaf.json").read_bytes()
    git(seed, "rm", "-r", "nested")
    (seed / "nested").write_text("now a file\n")
    commit_all(seed)
    git(seed, "push", "origin", "master")
    result = run(project, "pull")
    assert result.exit_code != 0 and "contains workspace files" in result.output
    assert draft.read_text() == "local ignored draft\n"
    assert (project / "paper/overleaf.json").read_bytes() == record


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
