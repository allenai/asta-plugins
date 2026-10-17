"""Version gating over a real local Git remote; hosted credentials are never used."""

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
            origin if str(arg).startswith("https://github.com/") else arg
            for arg in args
        )
        return original_git(*args, **kwargs)

    def gh(root, *args, **kwargs):
        return {"nameWithOwner": "org/scratch" if "org/check" in args else "org/paper"}

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

    def run(repo="org/check"):
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
    run, events, _ = runner
    monkeypatch.setattr(
        gate.sync, "gh", lambda *a, **kw: {"nameWithOwner": "org/paper"}
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
