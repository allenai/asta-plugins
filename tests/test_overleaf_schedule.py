"""Scheduled sync: the record's schedule setting and `sync --scheduled`."""

import importlib
import json

from tests.test_workspace_overleaf import URL, commit_all, git, run
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


def test_owner_repos_keeps_scheduled_only_and_reports_unreadable(monkeypatch):
    import base64

    def encoded(data):
        return {"encoding": "base64", "content": base64.b64encode(data).decode()}

    def tree(name):
        return f"repos/o/{name}/git/trees/main:.asta/overleaf?recursive=1"

    paper = {"tree": [{"type": "blob", "path": "paper.json", "sha": "s"}]}
    responses = {
        ("repo", "list"): [
            {"nameWithOwner": f"o/{name}", "defaultBranchRef": {"name": "main"}}
            for name in ("on", "off", "none", "broken", "big")
        ]
        + [{"nameWithOwner": "o/empty", "defaultBranchRef": None}],
        tree("on"): paper,
        tree("off"): paper,
        tree("big"): {"truncated": True, "tree": []},
        "repos/o/on/git/blobs/s": encoded(b'{"schedule": true}'),
        "repos/o/off/git/blobs/s": encoded(b"{}"),
    }

    def fake(*args, not_found=schedule._RAISE):
        key = args[:2] if args[0] == "repo" else args[1]
        if key in responses:
            return responses[key]
        if key == tree("none") and not_found is not schedule._RAISE:
            return not_found
        raise ov.SyncError("gh api failed: HTTP 502")

    monkeypatch.setattr(schedule, "gh_json", fake)
    found = dict(schedule.owner_repos("o"))
    assert set(found) == {"o/on", "o/broken", "o/big"}
    assert found["o/on"] is None
    assert "HTTP 502" in found["o/broken"] and "truncated" in found["o/big"]
