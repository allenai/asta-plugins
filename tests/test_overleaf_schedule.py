"""Scheduled sync: the record's schedule setting and `sync --scheduled`."""

import base64
import importlib
import json
import subprocess

import pytest

from tests.test_overleaf_sync import github as github  # noqa: F401
from tests.test_workspace_overleaf import URL, commit_all, git, overleaf_edit, run
from tests.test_workspace_overleaf import setup as setup  # noqa: F401

ov = importlib.import_module("asta.commands.overleaf")
schedule = importlib.import_module("asta.commands.overleaf_schedule")
sync_module = importlib.import_module("asta.commands.overleaf_sync")


def record(project, directory="paper"):
    return json.loads((project / f".asta/overleaf/{directory}.json").read_text())


def test_scheduled_reads_only_true():
    assert schedule.scheduled(b'{"schedule": true}')
    for raw in (None, b"{}", b'{"schedule": "daily"}', b"[]", b"not json"):
        assert not schedule.scheduled(raw)


def test_pull_sets_and_clears_schedule(setup):
    _, project = setup
    assert run(project, "pull", URL, "--schedule").exit_code == 0
    assert record(project)["schedule"] is True
    commit_all(project)
    assert schedule.scheduled_directories(project) == ["paper"]

    assert run(project, "pull", "--no-schedule").exit_code == 0
    assert "schedule" not in record(project)
    commit_all(project)
    assert schedule.scheduled_directories(project) == []


def test_pull_without_flag_keeps_schedule(setup):
    _, project = setup
    assert run(project, "pull", URL, "--schedule").exit_code == 0
    commit_all(project)
    assert run(project, "pull").exit_code == 0
    assert record(project)["schedule"] is True


def test_uncommitted_schedule_is_ignored(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    path = project / ".asta/overleaf/paper.json"
    path.write_text(json.dumps({**record(project), "schedule": True}))
    assert schedule.scheduled_directories(project) == []


def test_local_checkouts(tmp_path):
    for name in ("b", "a"):
        git(tmp_path, "init", "-q", name)
    (tmp_path / "plain").mkdir()
    assert schedule.local_checkouts(tmp_path) == [tmp_path / "a", tmp_path / "b"]
    assert schedule.local_checkouts(tmp_path / "a") == [tmp_path / "a"]


def test_sync_scheduled_carries_on_past_a_failure(setup, monkeypatch, tmp_path):
    _, project = setup
    assert run(project, "pull", URL, "--schedule").exit_code == 0
    commit_all(project)
    other = tmp_path / "other"
    git(tmp_path, "init", "-q", "-b", "main", "other")
    (other / ".asta/overleaf").mkdir(parents=True)
    (other / ".asta/overleaf/paper.json").write_text(
        json.dumps({**record(project), "schedule": True})
    )
    commit_all(other)
    unscheduled = tmp_path / "unscheduled"
    git(tmp_path, "init", "-q", "-b", "main", "unscheduled")
    (unscheduled / ".asta/overleaf").mkdir(parents=True)
    (unscheduled / ".asta/overleaf/paper.json").write_text(
        json.dumps({k: v for k, v in record(project).items() if k != "schedule"})
    )
    commit_all(unscheduled)

    visited = []

    def fake_sync(root, directory):
        visited.append(root.name)
        if root.name == "other":
            raise ov.SyncError("boom")
        return sync_module.COMPLETE, "done"

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", "--scheduled")
    assert sorted(visited) == ["other", project.name]
    assert result.exit_code != 0
    assert "other" in result.output and "All scheduled papers were attempted" in (
        result.output
    )


def test_sync_scheduled_reports_none_found(tmp_path):
    result = run(tmp_path, "sync", "--scheduled")
    assert result.exit_code == 0
    assert "No paper with schedule turned on" in result.output


def test_owner_requires_scheduled(tmp_path):
    result = run(tmp_path, "sync", "--owner", "allenai")
    assert result.exit_code == 2


def test_owner_repos_keeps_scheduled_only(monkeypatch):
    responses = {
        "graphql": [
            repo_node("on"),
            repo_node("off"),
            repo_node("none"),
            repo_node("broken"),
            repo_node("big"),
            repo_node("empty", defaultBranchRef=None),
        ],
        "repos/o/on/git/trees/main%3A.asta%2Foverleaf?recursive=1": {
            "tree": [{"type": "blob", "path": "paper.json", "sha": "s"}]
        },
        "repos/o/off/git/trees/main%3A.asta%2Foverleaf?recursive=1": {
            "tree": [{"type": "blob", "path": "paper.json", "sha": "s"}]
        },
        "repos/o/big/git/trees/main%3A.asta%2Foverleaf?recursive=1": {
            "truncated": True
        },
        "repos/o/on/git/blobs/s": encoded(b'{"schedule": true}'),
        "repos/o/off/git/blobs/s": encoded(b"{}"),
    }

    def fake(*args, not_found=schedule._RAISE, **kwargs):
        if args[1] == "repos/o/none/git/trees/main%3A.asta%2Foverleaf?recursive=1":
            assert not_found is not schedule._RAISE
            return not_found
        if args[1] == "repos/o/broken/git/trees/main%3A.asta%2Foverleaf?recursive=1":
            raise ov.SyncError("HTTP 502")
        return responses[args[1]]

    monkeypatch.setattr(schedule, "gh_json", fake)
    found = dict(schedule.owner_repos("o"))
    assert set(found) == {"o/on", "o/broken", "o/big"}
    assert found["o/on"] is None
    assert "HTTP 502" in found["o/broken"]
    assert "truncated" in found["o/big"]


def encoded(data):
    return {"encoding": "base64", "content": base64.encodebytes(data).decode()}


def repo_node(name, **kwargs):
    return {
        "nameWithOwner": f"o/{name}",
        "defaultBranchRef": {"name": "main"},
        "isArchived": False,
        **kwargs,
    }


@pytest.mark.parametrize(
    "state",
    [
        sync_module.COMPLETE,
        sync_module.WAITING,
        sync_module.PERSON,
        sync_module.LOCKED,
    ],
)
def test_scheduled_preserves_single_pass_scheduler_outcomes(setup, monkeypatch, state):
    _, project = setup
    assert run(project, "pull", URL, "--schedule").exit_code == 0
    commit_all(project)

    def fake_sync(root, directory):
        assert root == project and directory == "paper"
        return state, "normal scheduler outcome"

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(project, "sync", "--scheduled")
    assert result.exit_code == 0, result.output
    assert "No paper with schedule" not in result.output


@pytest.mark.parametrize("owner", [None, "o"])
def test_scheduled_uses_environment_identity_in_a_fresh_clone(
    setup, github, monkeypatch, owner
):
    seed, project = setup
    assert run(project, "pull", URL, "--schedule").exit_code == 0
    commit_all(project)
    git(project, "push", "origin", "main")
    overleaf_edit(seed, "main.tex", "co-author edit\n")
    if owner:
        monkeypatch.setattr(schedule, "owner_repos", lambda name: [("o/paper", None)])

        def clone(name, dest):
            git(project, "clone", str(project.parent / "workspace.git"), str(dest))
            return dest

        monkeypatch.setattr(schedule, "clone", clone)
    # No user.* configuration: the runner supplies GIT_AUTHOR_*/GIT_COMMITTER_*.
    result = run(project, "sync", "--scheduled", *(["--owner", owner] if owner else []))
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    assert "waiting for checks" in result.output


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing", "json"])
def test_gh_discovery_failures_are_reported_without_transport_diagnostics(
    monkeypatch, failure
):
    def fake_run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("gh", 90, stderr=b"private diagnostic")
        if failure == "missing":
            raise FileNotFoundError("private diagnostic")
        return subprocess.CompletedProcess(
            args[0],
            1 if failure == "exit" else 0,
            stdout=b"private diagnostic",
            stderr=b"private diagnostic",
        )

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    with pytest.raises(ov.SyncError, match="GitHub discovery") as exc:
        schedule.gh_json(
            "api", "repos/o/r/git/trees/main%3A.asta%2Foverleaf?recursive=1"
        )
    assert "private diagnostic" not in str(exc.value)


def test_only_an_explicitly_optional_directory_read_accepts_404(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 1, stdout=b"", stderr=b"gh: Not Found (HTTP 404)"
        )

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    assert schedule.gh_json("api", "missing-directory", not_found={}) == {}
    with pytest.raises(ov.SyncError, match="GitHub discovery request failed"):
        schedule.gh_json("api", "missing-blob")


@pytest.mark.parametrize("failure", ["tree", "record", "truncated", "encoding"])
def test_owner_discovery_failure_is_nonzero_and_other_papers_are_synced(
    tmp_path, monkeypatch, failure
):
    attempted = []

    def fake(*args, **kwargs):
        endpoint = args[1]
        if endpoint == "graphql":
            return [repo_node("bad"), repo_node("good")]
        bad = endpoint.startswith("repos/o/bad/")
        if "/git/trees/" in endpoint:
            if bad and failure == "tree":
                raise ov.SyncError("tree request failed")
            return {
                "tree": [{"type": "blob", "path": "paper.json", "sha": "s"}],
                "truncated": bad and failure == "truncated",
            }
        assert "/git/blobs/" in endpoint
        if bad and failure == "record":
            raise ov.SyncError("record request failed")
        if bad and failure == "encoding":
            return {"encoding": "base64", "content": "not base64!"}
        return encoded(b'{"schedule": true}')

    def fake_sync(root, directory):
        attempted.append((root.name, directory))
        return sync_module.COMPLETE, "done"

    monkeypatch.setattr(schedule, "gh_json", fake)
    monkeypatch.setattr(schedule, "clone", lambda name, dest: dest)
    monkeypatch.setattr(schedule, "scheduled_directories", lambda root: ["paper"])
    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", "--scheduled", "--owner", "o")
    assert result.exit_code == 1, result.output
    assert "o/bad" in result.output
    assert "All scheduled papers were attempted" in result.output
    assert attempted == [("o__good", "paper")]


def test_owner_discovery_consumes_all_repository_pages(monkeypatch):
    listed = [repo_node(str(i)) for i in range(1000)] + [repo_node("scheduled")]
    visited = []

    def fake(*args, **kwargs):
        assert args[:2] == ("api", "graphql")
        assert "--paginate" in args and "--jq" in args
        assert "login=o" in args and kwargs["lines"]
        return listed

    def is_scheduled(name, branch):
        visited.append(name)
        return name == "o/scheduled"

    monkeypatch.setattr(schedule, "gh_json", fake)
    monkeypatch.setattr(schedule, "repo_scheduled", is_scheduled)
    assert list(schedule.owner_repos("o")) == [("o/scheduled", None)]
    assert len(visited) == 1001


def test_owner_listing_failure_is_not_no_papers_found(tmp_path, monkeypatch):
    def fake(*args, **kwargs):
        raise ov.SyncError("GitHub discovery request failed")

    monkeypatch.setattr(schedule, "gh_json", fake)
    result = run(tmp_path, "sync", "--scheduled", "--owner", "o")
    assert result.exit_code == 1
    assert "GitHub discovery request failed" in result.output
    assert "No paper with schedule" not in result.output


def test_gh_json_reads_paginated_json_lines(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 0, stdout=b'{"name": "first"}\n{"name": "last"}\n', stderr=b""
        )

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    assert schedule.gh_json("api", "graphql", lines=True) == [
        {"name": "first"},
        {"name": "last"},
    ]
