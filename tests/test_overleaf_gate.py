"""Version gating over a real local Git remote; hosted credentials are never used."""

import hashlib
import importlib

import pytest
from click.testing import CliRunner

from asta.cli import cli
from tests.test_overleaf_sync import github as github  # noqa: F401
from tests.test_overleaf_sync import prepare
from tests.test_workspace_overleaf import git
from tests.test_workspace_overleaf import setup as setup  # noqa: F401

gate = importlib.import_module("asta.commands.overleaf_gate")


@pytest.fixture
def runner(setup, github, monkeypatch):
    _, project = prepare(setup)
    original_git = gate.ov.git
    original_config = gate.ov.load_config
    origin = git(project, "remote", "get-url", "origin")
    events = []

    def local_git(*args, **kwargs):
        args = tuple(
            origin
            if str(arg).startswith(
                (
                    "https://github.com/",
                    "https://git.example.test/",
                    "git@git.example.test:",
                )
            )
            else arg
            for arg in args
        )
        return original_git(*args, **kwargs)

    def gh(root, *args, **kwargs):
        name = (
            "org/scratch"
            if any(str(arg).endswith("/org/check") for arg in args)
            else "org/paper"
        )
        return {
            "nameWithOwner": name,
            "url": f"https://github.com/{name}",
            "sshUrl": f"git@github.com:{name}.git",
        }

    def config(path):
        value = original_config(path)
        if path == project / "paper":
            value = dict(value, url="https://git.overleaf.com/" + "f" * 24)
        return value

    monkeypatch.setattr(gate.ov, "git", local_git)
    monkeypatch.setattr(gate.ov, "load_config", config)
    monkeypatch.setattr(gate.sync, "gh", gh)
    monkeypatch.setattr(gate, "check_workspace", lambda *args: events.append("check"))
    monkeypatch.setattr(
        gate.sync, "sync_workspace", lambda *args: events.append("paper")
    )

    def run(repo="org/check", *extra):
        return CliRunner().invoke(
            cli,
            [
                "workspace",
                "overleaf",
                "sync",
                "--project",
                str(project),
                "--check-repo",
                repo,
                *extra,
            ],
        )

    return run, events, project


def test_pass_once_per_version_before_paper(runner, monkeypatch):
    run, events, _ = runner
    assert run().exit_code == 0
    assert events == ["check", "paper"]
    assert run().exit_code == 0
    assert events == ["check", "paper", "paper"]
    monkeypatch.setattr(gate, "__version__", "next-version")
    assert run().exit_code == 0
    assert events[-2:] == ["check", "paper"]


def test_failure_never_syncs_or_caches(runner, monkeypatch):
    run, events, project = runner

    def fail(*args):
        raise gate.ov.SyncError("Overleaf check failed (release step): conflict merge")

    monkeypatch.setattr(gate, "check_workspace", fail)
    result = run()
    assert result.exit_code != 0
    assert "release step" in result.output
    assert events == []
    assert not git(project, "ls-remote", "origin", "refs/tags/asta-overleaf-check/*")


@pytest.mark.parametrize("repo", ["org/paper", "ORG/PAPER"])
def test_same_canonical_repo_refused_even_when_cached(runner, monkeypatch, repo):
    run, events, project = runner
    ref = (
        "refs/tags/asta-overleaf-check/"
        + hashlib.sha256(gate.__version__.encode()).hexdigest()
    )
    git(project, "push", "origin", f"HEAD:{ref}")
    monkeypatch.setattr(
        gate.sync,
        "gh",
        lambda *a, **kw: {
            "nameWithOwner": "org/paper",
            "url": "https://github.com/org/paper",
        },
    )
    result = run(repo)
    assert result.exit_code != 0
    assert "paper being synced" in result.output
    assert events == []


def test_lookup_access_failure_is_actionable(runner, monkeypatch):
    run, events, _ = runner
    original = gate.ov.git

    def fail(*args, **kwargs):
        if "ls-remote" in args:
            raise gate.ov.SyncError("Cannot access remote")
        return original(*args, **kwargs)

    monkeypatch.setattr(gate.ov, "git", fail)
    result = run()
    assert result.exit_code != 0
    assert "pair access/setup" in result.output
    assert events == []


def test_record_failure_blocks_paper(runner, monkeypatch):
    run, events, _ = runner
    original = gate.ov.git

    def fail(*args, **kwargs):
        if "push" in args:
            raise gate.ov.SyncError("Cannot write pass record")
        return original(*args, **kwargs)

    monkeypatch.setattr(gate.ov, "git", fail)
    result = run()
    assert result.exit_code != 0
    assert "could not record" in result.output
    assert events == ["check"]


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize(
    "url",
    [
        "https://git.overleaf.com/1234567",
        "https://git.overleaf.com/1234567/",
        "https://git.overleaf.com/1234567.git",
        "https://git@git.overleaf.com/1234567.git/",
    ],
)
def test_same_overleaf_project_refused_before_check_or_paper(
    runner, monkeypatch, cached, url
):
    run, events, project = runner
    if cached:
        assert run().exit_code == 0
    before = list(events)
    refs = git(project, "ls-remote", "origin")
    original = gate.ov.load_config

    def paired(path):
        value = original(path)
        return dict(value, url=url) if path == project / "paper" else value

    monkeypatch.setattr(gate.ov, "load_config", paired)
    result = run()
    assert result.exit_code != 0
    assert "paper's Overleaf project" in result.output
    assert events == before
    assert git(project, "ls-remote", "origin") == refs


@pytest.mark.parametrize("ssh", [False, True])
def test_check_clone_uses_repository_host_and_origin_transport(
    runner, monkeypatch, ssh
):
    run, events, project = runner
    original = gate.ov.git
    clones = []
    lookups = []

    def gh(root, *args):
        lookups.append(args)
        name = (
            "org/scratch"
            if "https://git.example.test/org/check" in args
            else "org/paper"
        )
        return {
            "nameWithOwner": name,
            "url": f"https://git.example.test/{name}",
            "sshUrl": f"git@git.example.test:{name}.git",
        }

    def git_call(*args, **kwargs):
        if args == ("remote", "get-url", "origin") and kwargs["cwd"] == project:
            return (
                "git@git.example.test:org/paper.git"
                if ssh
                else "https://git.example.test/org/paper.git"
            )
        if args[0] == "clone":
            clones.append(args[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(gate.sync, "gh", gh)
    monkeypatch.setattr(gate.ov, "git", git_call)
    result = run()
    assert result.exit_code == 0, result.output
    expected = (
        "git@git.example.test:org/scratch.git"
        if ssh
        else "https://git.example.test/org/scratch.git"
    )
    assert clones == [expected]
    assert any("https://git.example.test/org/check" in args for args in lookups)
    assert events == ["check", "paper"]


def test_check_timeout_is_forwarded(runner, monkeypatch):
    run, events, _ = runner
    timeouts = []
    monkeypatch.setattr(
        gate,
        "check_workspace",
        lambda root, directory, timeout: timeouts.append(timeout),
    )
    result = run("org/check", "--check-timeout", "42")
    assert result.exit_code == 0, result.output
    assert timeouts == [42]
    assert events == ["paper"]


@pytest.mark.parametrize("cached", [False, True])
def test_project_id_case_variants_are_conservatively_isolated(
    runner, monkeypatch, cached
):
    run, events, project = runner
    if cached:
        assert run().exit_code == 0
    before = list(events)
    original = gate.ov.load_config

    def config(path):
        value = original(path)
        project_id = "ABCd123.git/" if path == project / "paper" else "abcd123"
        return dict(value, url="https://git.overleaf.com/" + project_id)

    monkeypatch.setattr(gate.ov, "load_config", config)
    result = run()
    assert result.exit_code != 0
    assert "paper's Overleaf project" in result.output
    assert events == before


@pytest.mark.parametrize("cached", [False, True])
def test_unpaired_paper_refused_before_any_scratch_access(runner, monkeypatch, cached):
    run, events, project = runner
    if cached:
        assert run().exit_code == 0
    before = list(events)
    refs = git(project, "ls-remote", "origin")
    original = gate.ov.load_config

    def unpaired(path):
        return None if path == project / "paper" else original(path)

    def no_github(*args, **kwargs):
        pytest.fail("an unpaired paper must be refused before GitHub access")

    monkeypatch.setattr(gate.ov, "load_config", unpaired)
    monkeypatch.setattr(gate.sync, "gh", no_github)
    result = run()
    assert result.exit_code != 0
    assert "pair access/setup" in result.output and "overleaf pull" in result.output
    assert events == before
    assert git(project, "ls-remote", "origin") == refs
