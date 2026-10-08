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
    remote = tmp_path / "overleaf.git"
    original_git = module.git_bytes

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


def test_publish_round_trip_and_refuses_unpulled_edits(setup):
    remote, seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
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


def test_credentials_are_ephemeral_and_not_in_script(monkeypatch):
    monkeypatch.setenv("OVERLEAF_TOKEN", "fixture-token")
    with module.credentials() as env:
        from pathlib import Path

        script = Path(env["GIT_ASKPASS"])
        assert script.exists() and script.stat().st_mode & 0o777 == 0o700
        assert "fixture-token" not in script.read_text()
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert "http.followRedirects=false" in module.network_options(env)
        assert "credential.helper=" in module.network_options(env)
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
    assert result.exit_code == 1 and "Git operation failed" in result.output
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
    git(
        project,
        "update-index",
        "--assume-unchanged",
        "paper/main.tex",
        "references.bib",
    )
    (paper / "main.tex").write_text("unreviewed\n")
    (project / "references.bib").write_text("@misc{unreviewed}\n")
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
