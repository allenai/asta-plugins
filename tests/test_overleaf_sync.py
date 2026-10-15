"""Scheduler behavior over real workspace and Overleaf Git repositories."""

import importlib
import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.cli import cli
from tests.test_workspace_overleaf import URL, commit_all, git, overleaf_edit, run
from tests.test_workspace_overleaf import setup as setup  # noqa: F401

sync = importlib.import_module("asta.commands.overleaf_sync")


@pytest.fixture
def github(monkeypatch):
    state = {"prs": [], "issues": [], "merges": [], "writes": 0}

    def gh(root, *args, payload=None):
        if args[:2] == ("repo", "view"):
            return {
                "nameWithOwner": "allenai/test",
                "defaultBranchRef": {"name": "main"},
            }
        if args[:2] == ("label", "create"):
            return None
        if args[:2] == ("pr", "list"):
            return state["prs"]
        if args[:2] == ("pr", "view"):
            return state["prs"][0]
        if args[:2] == ("pr", "merge"):
            state["merges"].append(args)
            if not state.get("allow_merge"):
                raise AssertionError("merge was not expected")
            git(root, "fetch", "origin", "main", "asta/overleaf-sync/1234567")
            with sync.tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "merge"
                git(root, "clone", str(root.parent / "workspace.git"), str(dest))
                git(dest, "merge", "--squash", "origin/asta/overleaf-sync/1234567")
                bodyfile = args[args.index("--body-file") + 1]
                git(
                    dest,
                    "commit",
                    "-m",
                    "Sync Overleaf paper\n\n" + Path(bodyfile).read_text(),
                )
                git(dest, "push", "origin", "HEAD:main")
            state["prs"].clear()
            return None
        if args[0] == "api":
            if payload is None and "/issues?" in args[1]:
                return state["issues"]
            state["writes"] += 1
            if args[1].endswith("/pulls"):
                pr = {
                    "number": 1,
                    "url": "https://github.com/allenai/test/pull/1",
                    "body": payload["body"],
                    "baseRefName": "main",
                    "labels": [{"name": sync.LABEL}],
                    "headRefOid": git(
                        root,
                        "ls-remote",
                        "origin",
                        "refs/heads/asta/overleaf-sync/1234567",
                    ).split()[0],
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                }
                state["prs"].append(pr)
                return pr
            if "/pulls/" in args[1]:
                state["prs"][0]["body"] = payload["body"]
            elif args[1].endswith("/issues"):
                state["issues"].append({**payload, "number": 2})
            elif "/issues/2" in args[1]:
                state["issues"][0]["body"] = payload["body"]
            return None
        raise AssertionError(args)

    monkeypatch.setattr(sync, "gh", gh)
    return state


def invoke(project):
    return CliRunner().invoke(
        cli, ["workspace", "overleaf", "sync", "--project", str(project)]
    )


def prepare(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "config", "user.name", "t")
    git(project, "config", "user.email", "t@t")
    git(project, "push", "origin", "HEAD:main")
    return seed, project


def test_new_edits_create_one_pr_and_quiet_rerun_waits_for_checks(setup, github):
    seed, project = prepare(setup)
    original = git(project, "rev-parse", "HEAD")
    overleaf_edit(seed, "main.tex", "coauthor edit\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    assert not github["merges"]
    assert git(project, "rev-parse", "HEAD") == original
    assert git(project, "status", "--porcelain") == ""
    head = git(
        project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/1234567"
    ).split()[0]
    git(project, "fetch", "origin", head)
    assert "Co-authored-by: t <t@t>" in git(project, "show", "-s", "--format=%B", head)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    assert not github["merges"]
    writes = github["writes"]
    assert invoke(project).exit_code == 0
    assert github["writes"] == writes  # unchanged waiting status does not repeat


def test_conflict_is_left_in_pr_and_never_merged(setup, github):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("workspace edit\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    overleaf_edit(seed, "main.tex", "Overleaf edit\n")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert len(github["prs"]) == 1
    assert "author must resolve" in github["prs"][0]["body"]
    assert not github["merges"]
    assert not git(
        project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/1234567"
    )


def test_remote_lock_excludes_second_clone_and_releases_after_failure(setup):
    _, project = prepare(setup)
    with pytest.raises(RuntimeError):
        with sync.lock(project, "1234567") as acquired:
            assert acquired
            with sync.lock(project, "1234567") as second:
                assert not second
            raise RuntimeError("interrupted")
    with sync.lock(project, "1234567") as acquired:
        assert acquired


@pytest.mark.parametrize(
    "checks,expected",
    [
        ([], False),
        ([{"state": "PENDING"}], False),
        ([{"state": "FAILURE"}], False),
        ([{"state": "SUCCESS"}], True),
        ([{"status": "IN_PROGRESS", "conclusion": ""}], False),
        ([{"status": "COMPLETED", "conclusion": "FAILURE"}], False),
        ([{"status": "COMPLETED", "conclusion": "SKIPPED"}], False),
    ],
)
def test_checks_fail_closed(checks, expected):
    assert sync.checks_pass({"statusCheckRollup": checks}) == expected


@pytest.mark.parametrize("marker", ["<<<<<<< workspace", "=======", ">>>>>>> overleaf"])
def test_shared_check_refuses_paper_markers_before_render(tmp_path, marker):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "overleaf.json").write_text(json.dumps({"url": URL, "base": "0" * 40}))
    (paper / "main.tex").write_text(marker + "\n")
    git(tmp_path, "add", "paper/overleaf.json", "paper/main.tex")
    script = (
        Path(__file__).parents[1]
        / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
    )
    result = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "conflict markers" in result.stdout
    assert "quarto" not in result.stderr


def test_quiet_checked_pr_squashes_with_credit_then_reruns_without_new_pr(
    setup, github
):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "invited author content\n")
    assert invoke(project).exit_code == 0
    github["allow_merge"] = True
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["merges"]) == 1
    assert not github["prs"]
    git(project, "fetch", "origin", "main")
    assert "Co-authored-by: t <t@t>" in git(
        project, "show", "-s", "--format=%B", "FETCH_HEAD"
    )
    assert git(project, "show", "FETCH_HEAD:paper/main.tex") == "invited author content"
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert not github["prs"]


def test_published_metadata_only_pull_does_not_create_sync_pr(setup, github):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("published workspace text\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert not github["prs"]
    assert not github["merges"]


def test_new_edit_defers_a_previously_checked_pr(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "first edit\n")
    assert invoke(project).exit_code == 0
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    old = github["prs"][0]["headRefOid"]
    overleaf_edit(seed, "main.tex", "second edit\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert not github["merges"]
    assert (
        git(
            project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/1234567"
        ).split()[0]
        != old
    )
