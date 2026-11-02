"""Scheduled sync: the record's schedule setting and `sync --github-owner`."""

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


def test_first_pull_turns_schedule_on_by_default(setup):
    _, project = setup
    assert run(project, "pull", URL).exit_code == 0
    assert record(project)["schedule"] is True


def test_first_pull_with_no_schedule_stays_manual(setup):
    _, project = setup
    assert run(project, "pull", URL, "--no-schedule").exit_code == 0
    assert "schedule" not in record(project)
    commit_all(project)
    assert run(project, "pull").exit_code == 0
    assert "schedule" not in record(project)


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
    assert run(project, "pull", URL, "--no-schedule").exit_code == 0
    commit_all(project)
    path = project / ".asta/overleaf/paper.json"
    path.write_text(json.dumps({**record(project), "schedule": True}))
    assert schedule.scheduled_directories(project) == []


def found_locally(monkeypatch, repos):
    """Discovery finds these repos, and cloning one returns its local checkout."""
    monkeypatch.setattr(
        schedule, "owner_repos", lambda owner: [(n, None) for n in repos]
    )
    monkeypatch.setattr(schedule, "clone", lambda name, dest: repos[name])


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
    found_locally(
        monkeypatch, {"o/other": other, "o/paper": project, "o/off": unscheduled}
    )
    result = run(tmp_path, "sync", "--github-owner", "o")
    assert sorted(visited) == ["other", project.name]
    assert result.exit_code != 0
    assert "o/other" in result.output and "All scheduled papers were attempted" in (
        result.output
    )


def test_sync_scheduled_reports_none_found(tmp_path, monkeypatch):
    found_locally(monkeypatch, {})
    result = run(tmp_path, "sync", "--github-owner", "o")
    assert result.exit_code == 0
    assert "No paper with schedule turned on" in result.output


@pytest.mark.parametrize("args", [["--dir", "paper"], ["--wait", "60"]])
def test_github_owner_refuses_dir_and_wait(tmp_path, args):
    result = run(tmp_path, "sync", "--github-owner", "o", *args)
    assert result.exit_code == 2


def search_hit(repo, path=".asta/overleaf/paper.json"):
    return {"repo": f"o/{repo}", "path": path}


def search_page(*hits, total_count=None, incomplete_results=False):
    return {
        "total_count": len(hits) if total_count is None else total_count,
        "incomplete_results": incomplete_results,
        "items": [
            {"repository": {"full_name": hit["repo"]}, "path": hit["path"]}
            for hit in hits
        ],
    }


def encoded(data):
    return {"encoding": "base64", "content": base64.encodebytes(data).decode()}


def test_owner_repos_searches_once_and_confirms_each_record(monkeypatch):
    searches = []
    contents = {
        "repos/o/on/contents/.asta/overleaf/paper.json": encoded(b"{}"),
        "repos/o/on/contents/.asta/overleaf/nested/b.json": encoded(
            b'{"schedule": true}'
        ),
        "repos/o/off/contents/.asta/overleaf/paper.json": encoded(
            b'{"schedule": false}'
        ),
    }

    def fake(*args, not_found=schedule._RAISE, **kwargs):
        if "search/code" in args:
            searches.append(args)
            assert "--paginate" in args and "--slurp" in args and "--jq" not in args
            return [
                search_page(
                    search_hit("on"),
                    search_hit("on", ".asta/overleaf/nested/b.json"),
                    search_hit("off"),
                    search_hit("elsewhere", "docs/.asta/overleaf/paper.json"),
                    search_hit("gone"),
                    search_hit("broken"),
                )
            ]
        endpoint = args[1]
        if endpoint == "repos/o/gone/contents/.asta/overleaf/paper.json":
            assert not_found is not schedule._RAISE
            return not_found
        if endpoint == "repos/o/broken/contents/.asta/overleaf/paper.json":
            raise ov.SyncError("HTTP 502")
        return contents[endpoint]

    monkeypatch.setattr(schedule, "gh_json", fake)
    found = dict(schedule.owner_repos("o"))
    assert len(searches) == 1
    query = next(a for a in searches[0] if a.startswith("q="))
    assert query == "q=schedule path:.asta/overleaf extension:json user:o"
    assert found == {"o/on": None, "o/broken": found["o/broken"]}
    assert "HTTP 502" in found["o/broken"]


def github_points_at(monkeypatch, base, repos):
    """Point https://github.com/<repo>.git at local repos so the real clone runs."""
    config = base / "github-urls.gitconfig"
    config.write_text(
        "".join(
            f'[url "{(base / path).as_uri()}"]\n'
            f"\tinsteadOf = https://github.com/{name}.git\n"
            for name, path in repos.items()
        )
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


def test_clone_failure_is_that_repos_failure(setup, monkeypatch):
    _, project = setup
    assert run(project, "pull", URL, "--schedule").exit_code == 0
    commit_all(project)
    git(project, "push", "origin", "main")
    monkeypatch.setattr(
        schedule,
        "owner_repos",
        lambda name: [("o/missing", None), ("o/crash", None), ("o/paper", None)],
    )
    github_points_at(
        monkeypatch,
        project.parent,
        {"o/missing": "no-such.git", "o/paper": "workspace.git"},
    )
    real_clone = schedule.clone

    def clone(name, dest):
        if name == "o/crash":
            raise TypeError("bug")
        return real_clone(name, dest)

    monkeypatch.setattr(schedule, "clone", clone)
    visited = []

    def fake_sync(root, directory):
        visited.append(directory)
        return sync_module.COMPLETE, "done"

    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(project, "sync", "--github-owner", "o")
    assert visited == ["paper"]
    assert result.exit_code != 0
    assert "o/missing: git clone failed" in result.output
    assert "o/crash: unexpected TypeError" in result.output
    assert "Sync failed for: o/missing, o/crash." in result.output


def test_scheduled_uses_environment_identity_in_a_fresh_clone(
    setup, github, monkeypatch
):
    seed, project = setup
    assert run(project, "pull", URL, "--schedule").exit_code == 0
    commit_all(project)
    git(project, "push", "origin", "main")
    overleaf_edit(seed, "main.tex", "co-author edit\n")
    monkeypatch.setattr(schedule, "owner_repos", lambda name: [("o/paper", None)])
    github_points_at(monkeypatch, project.parent, {"o/paper": "workspace.git"})
    # The real clone runs; no user.* configuration: the runner supplies GIT_AUTHOR_*/GIT_COMMITTER_*.
    result = run(project, "sync", "--github-owner", "o")
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    assert "waiting for checks" in result.output


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
    found_locally(monkeypatch, {"o/paper": project})
    result = run(project, "sync", "--github-owner", "o")
    assert result.exit_code == 0, result.output
    assert "No paper with schedule" not in result.output


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
        schedule.gh_json("api", "repos/o/r/contents/.asta/overleaf/paper.json")
    assert "private diagnostic" not in str(exc.value)


def test_only_an_explicitly_optional_record_read_accepts_404(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 1, stdout=b"", stderr=b"gh: Not Found (HTTP 404)"
        )

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    assert schedule.gh_json("api", "missing-record", not_found={}) == {}
    with pytest.raises(ov.SyncError, match="GitHub discovery request failed"):
        schedule.gh_json("api", "search/code")


@pytest.mark.parametrize("failure", ["record", "encoding"])
def test_owner_discovery_failure_is_nonzero_and_other_papers_are_synced(
    tmp_path, monkeypatch, failure
):
    attempted = []

    def fake(*args, **kwargs):
        if "search/code" in args:
            return [search_page(search_hit("bad"), search_hit("good"))]
        bad = args[1].startswith("repos/o/bad/")
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
    result = run(tmp_path, "sync", "--github-owner", "o")
    assert result.exit_code == 1, result.output
    assert "o/bad" in result.output
    assert "All scheduled papers were attempted" in result.output
    assert attempted == [("o__good", "paper")]


def test_owner_listing_failure_is_not_no_papers_found(tmp_path, monkeypatch):
    def fake(*args, **kwargs):
        raise ov.SyncError("GitHub discovery request failed")

    monkeypatch.setattr(schedule, "gh_json", fake)
    result = run(tmp_path, "sync", "--github-owner", "o")
    assert result.exit_code == 1
    assert "GitHub discovery request failed" in result.output
    assert "No paper with schedule" not in result.output


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"incomplete_results": True}, "returned incomplete results"),
        ({"total_count": 1001}, "exceeds GitHub's 1,000-result limit"),
    ],
)
@pytest.mark.parametrize("bad_page", [0, 1])
def test_incomplete_search_fails_visibly_before_sync(
    tmp_path, monkeypatch, metadata, message, bad_page
):
    pages = [search_page(search_hit(repo), total_count=2) for repo in ("first", "last")]
    pages[bad_page].update(metadata)
    attempted = []

    def fake_run(args, **kwargs):
        if "search/code" in args:
            if "--jq" in args:
                # The old projection drops the metadata that signals missing papers.
                output = "\n".join(
                    json.dumps(search_hit(repo)) for repo in ("first", "last")
                )
            else:
                assert "--paginate" in args and "--slurp" in args
                output = json.dumps(pages)
        else:
            output = json.dumps(encoded(b'{"schedule": true}'))
        return subprocess.CompletedProcess(args, 0, stdout=output.encode(), stderr=b"")

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    monkeypatch.setattr(schedule, "clone", lambda name, dest: dest)
    monkeypatch.setattr(schedule, "scheduled_directories", lambda root: ["paper"])
    monkeypatch.setattr(
        sync_module, "sync_workspace", lambda root, directory: attempted.append(root)
    )
    result = run(tmp_path, "sync", "--github-owner", "o")
    assert result.exit_code == 1, result.output
    assert message in result.output
    assert "No paper with schedule" not in result.output
    assert attempted == []


@pytest.mark.parametrize("broken_first", [True, False])
@pytest.mark.parametrize("failure", ["request", "encoding"])
def test_unreadable_record_does_not_skip_other_papers_in_the_repo(
    tmp_path, monkeypatch, broken_first, failure
):
    hits = [
        search_hit("multi", f".asta/overleaf/{paper}.json") for paper in ("bad", "good")
    ]
    if not broken_first:
        hits.reverse()
    hits.append(search_hit("other"))
    reads = []
    attempted = []

    def fake(*args, **kwargs):
        if "search/code" in args:
            return [search_page(*hits)]
        endpoint = args[1]
        reads.append(endpoint)
        if endpoint.endswith("/bad.json"):
            if failure == "request":
                raise ov.SyncError("record request failed")
            return {"encoding": "base64", "content": "not base64!"}
        return encoded(b'{"schedule": true}')

    def fake_sync(root, directory):
        attempted.append((root.name, directory))
        return sync_module.COMPLETE, "done"

    monkeypatch.setattr(schedule, "gh_json", fake)
    monkeypatch.setattr(schedule, "clone", lambda name, dest: dest)
    monkeypatch.setattr(schedule, "scheduled_directories", lambda root: ["good"])
    monkeypatch.setattr(sync_module, "sync_workspace", fake_sync)
    result = run(tmp_path, "sync", "--github-owner", "o")
    assert attempted == [("o__multi", "good"), ("o__other", "good")]
    assert len(reads) == 3
    assert result.exit_code == 1, result.output
    assert (
        "o/multi: cannot read pairing record .asta/overleaf/bad.json" in result.output
    )
    assert "All scheduled papers were attempted" in result.output


def test_owner_discovery_reads_every_search_page(monkeypatch):
    hits = [search_hit("first"), search_hit("last")]
    pages = [search_page(hit, total_count=2) for hit in hits]
    reads = []

    def fake_run(*args, **kwargs):
        argv = args[0]
        if "search/code" in argv:
            assert "--paginate" in argv and "--slurp" in argv
            assert "--jq" not in argv
            output = pages
        else:
            reads.append(argv[2])
            output = encoded(b'{"schedule": true}')
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(output).encode(), stderr=b""
        )

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    assert schedule.owner_repos("o") == [("o/first", None), ("o/last", None)]
    assert reads == [
        "repos/o/first/contents/.asta/overleaf/paper.json",
        "repos/o/last/contents/.asta/overleaf/paper.json",
    ]


@pytest.mark.parametrize("count", [0, 1000])
def test_complete_search_accepts_zero_or_exactly_a_thousand_matches(monkeypatch, count):
    hits = [search_hit("many", f".asta/overleaf/paper{n}.json") for n in range(count)]
    pages = [
        search_page(*hits[start : start + 100], total_count=count)
        for start in range(0, max(count, 1), 100)
    ]
    reads = []

    def fake(*args, **kwargs):
        if "search/code" in args:
            return pages
        reads.append(args[1])
        return encoded(b'{"schedule": true}')

    monkeypatch.setattr(schedule, "gh_json", fake)
    assert schedule.owner_repos("o") == ([("o/many", None)] if count else [])
    assert len(reads) == count
