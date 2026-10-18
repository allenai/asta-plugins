"""Scheduler behavior over real workspace and Overleaf Git repositories."""

import ast
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.cli import cli
from tests.test_workspace_overleaf import URL, commit_all, git, overleaf_edit, run
from tests.test_workspace_overleaf import setup as setup  # noqa: F401

sync = importlib.import_module("asta.commands.overleaf_sync")


def _record(paper):
    """The pairing record for a paper directory directly under the workspace."""
    path = paper.parent / ".asta/overleaf" / f"{paper.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def github(monkeypatch):
    state = {"prs": [], "issues": [], "merges": [], "writes": 0, "calls": []}

    def gh(root, *args, payload=None):
        state["calls"].append((args, payload))
        if state.get("fail_report") and args[0] == "api":
            raise sync.ov.SyncError("fixture reporting failure")
        if args[:2] == ("repo", "view"):
            return {
                "nameWithOwner": "allenai/test",
                "defaultBranchRef": {"name": "main"},
            }
        if args[:2] == ("label", "create"):
            return None
        if args[:2] == ("pr", "list"):
            for pr in state["prs"]:
                pr["headRefOid"] = git(
                    root, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/1234567"
                ).split()[0]
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
            if payload is None and "/commits/" in args[1]:
                sha = args[1].rsplit("/", 1)[1]
                return {
                    "html_url": f"https://github.com/allenai/test/commit/{sha}",
                    "author": {"login": "workspace-author"},
                }
            if payload is None and "/issues?" in args[1]:
                return [state["issues"]] if "--slurp" in args else state["issues"]
            state["writes"] += 1
            if args[1].endswith("/pulls"):
                if state.pop("fail_create", False):
                    raise sync.ov.SyncError("fixture PR creation failure")
                pr = {
                    "isCrossRepository": False,
                    "headRepositoryOwner": {"login": "allenai"},
                    "number": 1,
                    "url": "https://github.com/allenai/test/pull/1",
                    "body": payload["body"],
                    "baseRefName": "main",
                    "labels": [],
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
            if args[1].endswith("/labels"):
                if state.pop("fail_label", False):
                    raise sync.ov.SyncError("fixture labeling failure")
                state["prs"][0]["labels"] = [{"name": sync.LABEL}]
            elif "/pulls/" in args[1]:
                state["prs"][0]["body"] = payload["body"]
            elif args[1].endswith("/issues"):
                state["issues"].append({**payload, "number": 2})
            elif "/issues/2" in args[1]:
                state["issues"][0].update(payload)
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
    assert "Opened https://github.com/allenai/test/pull/1;" in result.output
    assert "Copied Overleaf commit" not in result.output
    assert "open a PR" not in result.output
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_sync_works_with_symlinked_temporary_ancestor(setup, github, monkeypatch):
    seed, project = prepare(setup)
    original = git(project, "rev-parse", "HEAD")
    overleaf_edit(seed, "main.tex", "coauthor edit\n")
    physical = project.parent / "physical-tmp"
    physical.mkdir()
    alias = project.parent / "tmp-alias"
    alias.symlink_to(physical, target_is_directory=True)
    temporary_directory = sync.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        sync.tempfile,
        "TemporaryDirectory",
        lambda *args, **kwargs: temporary_directory(*args, dir=alias, **kwargs),
    )

    for _ in range(2):
        result = invoke(project)
        assert result.exit_code == 0, result.output
        assert len(github["prs"]) == 1
        assert not github["merges"]
        assert not git(
            project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/1234567"
        )
    assert git(project, "rev-parse", "HEAD") == original
    assert git(project, "status", "--porcelain") == ""
    head = github["prs"][0]["headRefOid"]
    git(project, "fetch", "origin", head)
    assert git(project, "show", f"{head}:paper/main.tex") == "coauthor edit"


def test_conflict_is_left_in_pr_and_never_merged(setup, github):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("workspace edit\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    overleaf_edit(seed, "main.tex", "Overleaf edit\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    body = github["prs"][0]["body"]
    assert body.startswith(sync.CONFLICT_BODY)
    assert "Nothing to do" not in body
    line = body.removeprefix(sync.CONFLICT_BODY).strip()
    assert "\n" not in line
    assert "by @workspace-author" in line
    assert "Fixes pushed to this branch are kept" in line
    assert line.endswith(
        "https://github.com/allenai/asta-plugins/blob/main/plugins/asta-tools/skills/workspace/workflows/overleaf-recovery.md#conflict-markers-after-pull-exit-3"
    )
    assert "mergeStateStatus" not in line and "checks" not in line.lower()
    assert "author must resolve" in result.output
    assert not github["merges"]
    assert not git(
        project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/1234567"
    )
    # A fix pushed to the sync branch is kept, and the conflict line goes away.
    branch = "asta/overleaf-sync/1234567"
    git(project, "fetch", "origin", branch)
    git(project, "checkout", "-B", "resolve", f"origin/{branch}")
    (project / "paper/main.tex").write_text("workspace edit\nOverleaf edit\n")
    commit_all(project)
    git(project, "push", "origin", f"HEAD:{branch}")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert github["prs"][0]["body"] == sync.DEFAULT_BODY
    git(project, "fetch", "origin", branch)
    assert git(project, "show", f"origin/{branch}:paper/main.tex") == (
        "workspace edit\nOverleaf edit"
    )


def test_resolved_conflict_line_is_removed_before_merge(setup, github):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("workspace edit\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    overleaf_edit(seed, "main.tex", "Overleaf edit\n")
    assert invoke(project).exit_code == 0
    pr = github["prs"][0]
    assert pr["body"].startswith(sync.CONFLICT_BODY)
    branch = "asta/overleaf-sync/1234567"
    git(project, "fetch", "origin", branch)
    git(project, "checkout", "-B", "resolve", f"origin/{branch}")
    (project / "paper/main.tex").write_text("workspace edit\nOverleaf edit\n")
    commit_all(project)
    git(project, "push", "origin", f"HEAD:{branch}")
    github["allow_merge"] = True
    pr["statusCheckRollup"] = [{"state": "SUCCESS"}]
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["merges"]) == 1
    assert pr["body"] == sync.DEFAULT_BODY


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
        (
            [{"state": "SUCCESS"}, {"status": "COMPLETED", "conclusion": "SKIPPED"}],
            True,
        ),
        (
            [{"state": "SUCCESS"}, {"status": "COMPLETED", "conclusion": "SUCCESS"}],
            True,
        ),
        (
            [{"state": "FAILURE"}, {"status": "COMPLETED", "conclusion": "SUCCESS"}],
            False,
        ),
        ([{"state": "SUCCESS"}, {"status": "IN_PROGRESS", "conclusion": ""}], False),
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
    _record(paper).write_text(json.dumps({"url": URL, "base": "0" * 40}))
    (paper / "main.tex").write_text(marker + "\n")
    git(tmp_path, "add", ".asta/overleaf/paper.json", "paper/main.tex")
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


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("shallow", [False, True])
def test_quiet_checked_pr_squashes_with_credit_then_reruns_without_new_pr(
    setup, github, monkeypatch, shallow
):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("published workspace text\n")
    commit_all(project)
    with monkeypatch.context() as identity:
        identity.setenv("GIT_AUTHOR_NAME", "Sync runner")
        identity.setenv("GIT_AUTHOR_EMAIL", "runner@example.invalid")
        identity.setenv("GIT_COMMITTER_NAME", "Sync runner")
        identity.setenv("GIT_COMMITTER_EMAIL", "runner@example.invalid")
        published = run(project, "publish")
    assert published.exit_code == 0, published.output
    if shallow:
        source = git(project, "rev-parse", "HEAD")
        (project / "notes.txt").write_text("Unrelated workspace change\n")
        commit_all(project)
        git(project, "push", "origin", "HEAD:main")
        checkout = project.parent / "shallow"
        git(
            project,
            "clone",
            "--depth=1",
            (project.parent / "workspace.git").as_uri(),
            str(checkout),
        )
        assert git(checkout, "rev-parse", "--is-shallow-repository") == "true"
        assert sync.ov.resolve_commit(checkout, source) is None
        git(checkout, "config", "user.name", "t")
        git(checkout, "config", "user.email", "t@t")
        project = checkout
    overleaf_edit(seed, "main.tex", "invited author content\n")
    imported = invoke(project)
    assert imported.exit_code == 0, imported.output
    github["allow_merge"] = True
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["merges"]) == 1
    assert not github["prs"]
    git(project, "fetch", "origin", "main")
    body = git(project, "show", "-s", "--format=%B", "FETCH_HEAD")
    assert "Co-authored-by: t <t@t>" in body
    assert "Sync runner" not in body
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


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_publish_failure_after_merge_opens_deduplicated_issue(
    setup, github, monkeypatch
):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready to merge\n")
    assert invoke(project).exit_code == 0
    github["allow_merge"] = True
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]

    def fail_publish(*args, **kwargs):
        raise sync.ov.SyncError("fixture publication race")

    monkeypatch.setattr(sync.ov.publish, "callback", fail_publish)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "fixture publication race" in result.output
    assert len(github["merges"]) == 1
    assert not github["prs"]
    assert len(github["issues"]) == 1
    assert "fixture publication race" in github["issues"][0]["body"]
    writes = github["writes"]
    assert invoke(project).exit_code == 1
    assert len(github["issues"]) == 1
    assert github["writes"] == writes


def test_failed_label_is_repaired_on_next_run(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    github["fail_label"] = True
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert len(github["prs"]) == 1
    assert github["prs"][0]["labels"] == []
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    assert github["prs"][0]["labels"] == [{"name": sync.LABEL}]


@pytest.mark.parametrize("merge_state", ["CLEAN", "BEHIND"])
def test_unrelated_default_edit_does_not_starve_checked_pr(setup, github, merge_state):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready paper\n")
    assert invoke(project).exit_code == 0
    pr = github["prs"][0]
    old = pr["headRefOid"]
    (project / "notes.txt").write_text("unrelated default content\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    pr["statusCheckRollup"] = [{"state": "SUCCESS"}]
    pr["mergeStateStatus"] = merge_state
    github["allow_merge"] = True
    result = invoke(project)
    assert result.exit_code == 0, result.output
    if merge_state == "CLEAN":
        assert len(github["merges"]) == 1
        git(project, "fetch", "origin", "main")
        assert (
            git(project, "show", "FETCH_HEAD:notes.txt") == "unrelated default content"
        )
    else:
        assert not github["merges"]
        assert (
            git(
                project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/1234567"
            ).split()[0]
            != old
        )


def test_pull_conflict_names_changed_file_commit_not_unrelated_paper_edit(
    setup, github
):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("workspace conflict\n")
    commit_all(project)
    culprit = git(project, "rev-parse", "HEAD")
    (project / "paper/old.tex").write_text("unrelated later paper edit\n")
    commit_all(project)
    unrelated = git(project, "rev-parse", "HEAD")
    git(project, "push", "origin", "HEAD:main")
    overleaf_edit(seed, "main.tex", "Overleaf conflict\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert culprit in github["prs"][0]["body"]
    assert unrelated not in github["prs"][0]["body"]
    assert "paper/main.tex" in result.output


def test_base_merge_conflict_names_changed_file_commit_not_default_tip(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "Overleaf conflict\n")
    assert invoke(project).exit_code == 0
    (project / "paper/main.tex").write_text("workspace conflict\n")
    commit_all(project)
    culprit = git(project, "rev-parse", "HEAD")
    (project / "notes.txt").write_text("unrelated last commit\n")
    commit_all(project)
    unrelated = git(project, "rev-parse", "HEAD")
    git(project, "push", "origin", "HEAD:main")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert culprit in github["prs"][0]["body"]
    assert unrelated not in github["prs"][0]["body"]


def test_unreported_conflict_still_fails(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "Overleaf conflict\n")
    assert invoke(project).exit_code == 0
    (project / "paper/main.tex").write_text("workspace conflict\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    github["fail_report"] = True
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "author must resolve" in result.output


@pytest.mark.parametrize("filename", ["latexmkrc", ".latexmkrc", "sub/latexmkrc"])
@pytest.mark.parametrize("open_pr", [False, True])
def test_build_configuration_refuses_before_push(setup, github, filename, open_pr):
    seed, project = prepare(setup)
    if open_pr:
        overleaf_edit(seed, "main.tex", "new edit\n")
        assert invoke(project).exit_code == 0
    old = git(project, "ls-remote", "origin", BRANCH)
    (seed / filename).parent.mkdir(parents=True, exist_ok=True)
    overleaf_edit(seed, filename, "$pdflatex = 'echo changed';\n")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "nothing pushed" in result.output
    assert git(project, "ls-remote", "origin", BRANCH) == old
    assert len(github["issues"]) == 1
    assert "person must review" in github["issues"][0]["body"]
    assert not github["merges"]
    writes = github["writes"]
    assert invoke(project).exit_code == 1
    assert github["writes"] == writes


def test_stale_lock_is_nonzero_and_reported_once(setup, github, monkeypatch):
    _, project = prepare(setup)
    with sync.lock(project, "1234567") as acquired:
        assert acquired
        created = int(git(project, "show", "-s", "--format=%ct", "HEAD"))
        monkeypatch.setattr(sync.time, "time", lambda: created + 7200)
        result = invoke(project)
        assert result.exit_code == 1, result.output
        assert "lock is held" in result.output
        assert len(github["issues"]) == 1
        writes = github["writes"]
        assert invoke(project).exit_code == 1
        assert github["writes"] == writes


def test_successful_update_clears_stale_failure_status(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "first edit\n")
    assert invoke(project).exit_code == 0
    sync.report(
        project, "allenai/test", "1234567", "old conflict refusal", github["prs"][0]
    )
    overleaf_edit(seed, "main.tex", "second edit\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert github["prs"][0]["body"] == sync.DEFAULT_BODY


def test_lock_release_error_preserves_original_failure(setup, monkeypatch):
    _, project = prepare(setup)
    original = sync.ov.git

    def fail_release(*args, **kwargs):
        if args[0] == "push" and ":refs/asta/overleaf-sync-lock/1234567" in args:
            raise sync.ov.SyncError("fixture release failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(sync.ov, "git", fail_release)
    with pytest.raises(RuntimeError, match="original failure"):
        with sync.lock(project, "1234567") as acquired:
            assert acquired
            raise RuntimeError("original failure")


def test_reporting_error_preserves_original_refusal(setup, github, monkeypatch):
    _, project = prepare(setup)

    def fail_pull(*args, **kwargs):
        github["fail_report"] = True
        raise sync.ov.SyncError("original pull failure")

    monkeypatch.setattr(sync, "pull_into", fail_pull)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "original pull failure" in result.output
    assert "fixture reporting failure" not in result.output


def test_missing_branch_configuration_reports_refusal(setup, github, tmp_path):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    assert invoke(project).exit_code == 0
    dest = tmp_path / "human"
    git(project, "clone", str(project.parent / "workspace.git"), str(dest))
    git(dest, "checkout", "asta/overleaf-sync/1234567")
    git(dest, "rm", ".asta/overleaf/paper.json")
    git(dest, "commit", "-m", "remove config")
    git(dest, "push", "origin", "HEAD:asta/overleaf-sync/1234567")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "restore the linked paper configuration" in result.output
    assert "restore the linked paper configuration" in github["prs"][0]["body"]


@pytest.mark.parametrize("key", ["user.name", "user.email"])
def test_missing_identity_is_explicit_and_reported(setup, github, monkeypatch, key):
    _, project = prepare(setup)
    git(project, "config", "--unset", key)
    monkeypatch.delenv("GIT_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("GIT_AUTHOR_EMAIL", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_NAME", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_EMAIL", raising=False)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert f"Configure Git {key}" in result.output
    assert len(github["issues"]) == 1
    assert not git(
        project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/1234567"
    )


def test_sync_rejects_root_and_sibling_paths(setup, github, monkeypatch, tmp_path):
    seed, project = prepare(setup)
    result = CliRunner().invoke(
        cli, ["workspace", "overleaf", "sync", "--project", str(project), "--dir", "."]
    )
    assert result.exit_code == 1, result.output
    assert not github["prs"]
    overleaf_edit(seed, "main.tex", "new edit\n")
    assert invoke(project).exit_code == 0
    dest = tmp_path / "human"
    git(project, "clone", str(project.parent / "workspace.git"), str(dest))
    git(dest, "checkout", "asta/overleaf-sync/1234567")
    (dest / "paper2").mkdir()
    (dest / "paper2/notes.tex").write_text("outside paper\n")
    commit_all(dest)
    git(dest, "push", "origin", "HEAD:asta/overleaf-sync/1234567")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "outside the paper" in result.output
    assert not github["merges"]


@pytest.mark.parametrize(
    "filename,data,blocked",
    [
        ("main.tex", b"<<<<<<<\r\n", True),
        ("main.tex", b"=======\r\n", True),
        ("main.tex", b">>>>>>>\r\n", True),
        ("main.tex", b"|||||||\r\n", True),
        ("main.tex", b">>>>>>> overleaf\r\n", True),
        ("notes.md", b"Heading\n=======\n", False),
        ("notes.md", b"<<<<<<< workspace\n", True),
        ("image.pdf", b"<<<<<<< workspace\n", False),
        ("main.tex", b"\0<<<<<<< workspace\n", False),
    ],
)
def test_marker_checks_agree_for_crlf_markdown_and_assets(
    tmp_path, filename, data, blocked
):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / "paper"
    paper.mkdir()
    _record(paper).write_text(json.dumps({"url": URL, "base": "0" * 40}))
    (paper / filename).write_bytes(data)
    git(tmp_path, "add", ".asta/overleaf/paper.json", "paper/" + filename)
    git(tmp_path, "commit", "-m", "fixture")
    assert bool(sync.conflict_files(tmp_path, "paper/")) == blocked
    script = (
        Path(__file__).parents[1]
        / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
    )
    result = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert ("Unresolved paper conflict markers" in result.stdout) == blocked


def test_shared_check_outside_git_has_no_traceback(tmp_path):
    script = (
        Path(__file__).parents[1]
        / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
    )
    result = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "Git checkout" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "directory", ["paper", "examples/paper", "research.v2/paper.draft"]
)
def test_shared_check_finds_conflicts_from_pairing_record_without_latexmkrc(
    tmp_path, directory
):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / directory
    paper.mkdir(parents=True)
    record = tmp_path / ".asta/overleaf" / f"{directory}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("{}")
    (paper / "main.tex").write_text("<<<<<<< workspace\n")
    git(tmp_path, "add", "--", directory, ".asta")
    result = subprocess.run(
        ["sh", str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "Unresolved paper conflict markers" in result.stdout
    assert f"{directory}/main.tex" in result.stdout
    assert "quarto" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX byte filenames")
def test_shared_check_handles_non_utf8_paths(tmp_path):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / "paper"
    paper.mkdir()
    _record(paper).write_text("{}")
    name = os.fsencode(paper) + b"/odd-\xff.tex"
    with open(name, "wb") as stream:
        stream.write(b"=======\r\n")
    git(tmp_path, "add", "--", "paper", ".asta")
    script = (
        Path(__file__).parents[1]
        / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
    )
    result = subprocess.run(["sh", str(script)], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1
    assert b"conflict markers" in result.stdout
    assert b"Traceback" not in result.stderr


BRANCH = "refs/heads/asta/overleaf-sync/1234567"
SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
)


def test_stale_lock_reports_on_open_sync_pr(setup, github, monkeypatch):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    assert invoke(project).exit_code == 0
    with sync.lock(project, "1234567") as acquired:
        assert acquired
        created = int(git(project, "show", "-s", "--format=%ct", "HEAD"))
        monkeypatch.setattr(sync.time, "time", lambda: created + 7200)
        result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "lock is held" in github["prs"][0]["body"]
    assert github["issues"] == []


def test_branch_pushed_before_pr_creation_is_recovered(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    github["fail_create"] = True
    assert invoke(project).exit_code == 1
    assert git(project, "ls-remote", "origin", BRANCH)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1


def test_unowned_reserved_branch_without_pr_is_not_replaced(setup, github):
    seed, project = prepare(setup)
    (project / "paper/notes.tex").write_text("someone's work\n")
    git(project, "add", "--", "paper/notes.tex")
    git(project, "commit", "-m", "Draft notes")
    git(project, "push", "origin", f"HEAD:{BRANCH}")
    theirs = git(project, "rev-parse", "HEAD")
    overleaf_edit(seed, "main.tex", "new edit\n")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "sync did not create" in result.output
    assert git(project, "ls-remote", "origin", BRANCH).split()[0] == theirs
    assert github["prs"] == [] and len(github["issues"]) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
@pytest.mark.parametrize("linked", ["file", "directory"])
def test_shared_check_never_follows_symlinks_out_of_checkout(tmp_path, linked):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "main.tex").write_bytes(b"<<<<<<< HEAD\n")
    repo = tmp_path / "repo"
    paper = repo / "paper"
    (paper / "sub").mkdir(parents=True)
    git(repo, "init", "-b", "main")
    _record(paper).write_text("{}")
    if linked == "file":
        (paper / "main.tex").symlink_to(outside / "main.tex")
    else:
        (paper / "sub/main.tex").write_text("clean\n")
    git(repo, "add", "--", "paper", ".asta")
    if linked == "directory":
        (paper / "sub/main.tex").unlink()
        (paper / "sub").rmdir()
        (paper / "sub").symlink_to(outside)
    result = subprocess.run(
        ["sh", str(SCRIPT)], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "not symlinks" in result.stdout
    assert "conflict markers" not in result.stdout


def test_shared_check_streams_long_lines(tmp_path):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / "paper"
    paper.mkdir()
    _record(paper).write_text("{}")
    (paper / "main.tex").write_bytes(b"x" * 200_000 + b"<<<<<<< not a line start\n")
    (paper / "refs.bib").write_bytes(b"y" * 200_000 + b"\n>>>>>>> theirs\n")
    git(tmp_path, "add", "--", "paper", ".asta")
    result = subprocess.run(
        ["sh", str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "paper/refs.bib" in result.stdout
    assert "paper/main.tex" not in result.stdout


def test_fresh_lock_preserves_conflict_status(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    assert invoke(project).exit_code == 0
    github["prs"][0]["body"] = "existing conflict guidance"
    writes = github["writes"]
    with sync.lock(project, "1234567"):
        result = invoke(project)
    assert result.exit_code == 0, result.output
    assert github["prs"][0]["body"] == "existing conflict guidance"
    assert github["writes"] == writes


@pytest.mark.parametrize(
    "cross,owner", [(True, "outsider"), (False, "outsider"), (True, "allenai")]
)
def test_foreign_pr_is_ignored(monkeypatch, tmp_path, cross, owner):
    foreign = {"isCrossRepository": cross, "headRepositoryOwner": {"login": owner}}
    local = {
        "isCrossRepository": False,
        "headRepositoryOwner": {"login": "allenai"},
        "body": sync.MARKER,
        "baseRefName": "main",
    }
    monkeypatch.setattr(sync, "gh", lambda *a: [foreign, local])
    assert sync.sync_pr(tmp_path, "allenai/test", "branch", "main") is local
    monkeypatch.setattr(sync, "gh", lambda *a: [foreign])
    assert sync.sync_pr(tmp_path, "allenai/test", "branch", "main") is None


@pytest.mark.parametrize(
    "state,action",
    [
        ("BLOCKED", "approvals"),
        ("UNSTABLE", "failing checks"),
        ("UNKNOWN", "computing"),
        ("DIRTY", "conflicts"),
    ],
)
def test_waiting_reports_actual_state(setup, github, state, action):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready\n")
    assert invoke(project).exit_code == 0
    github["prs"][0]["mergeStateStatus"] = state
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert github["prs"][0]["body"] == sync.DEFAULT_BODY
    assert "mergeStateStatus=" + state in result.output
    assert action in result.output


def test_waiting_without_checks_does_not_assume_ci_is_unconfigured(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready\n")
    assert invoke(project).exit_code == 0
    github["prs"][0]["mergeStateStatus"] = "CLEAN"
    github["prs"][0]["statusCheckRollup"] = []
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert "No checks have appeared yet" in result.output
    assert "If no checks are configured" in result.output
    assert "Wait for completed successful checks" not in result.output
    assert "Copied Overleaf commit" not in result.output
    assert not github["merges"]


@pytest.mark.parametrize("checks_appear", [False, True])
def test_sync_wait_allows_ci_checks_to_appear(
    setup, github, monkeypatch, checks_appear
):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready\n")
    assert invoke(project).exit_code == 0
    clock = [0.0]
    sleeps = []
    monkeypatch.setattr(sync.ov.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
        if checks_appear:
            github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
            github["allow_merge"] = True

    monkeypatch.setattr(sync.ov.time, "sleep", sleep)
    result = run(project, "sync", "--wait", "60")
    assert result.exit_code == (0 if checks_appear else 5), result.output
    assert sleeps == ([30] if checks_appear else [30, 30])
    assert len(github["merges"]) == int(checks_appear)
    assert "Sync outcome: a person must act" not in result.output
    assert git(project, "status", "--porcelain") == ""


def test_markerless_pull_conflict_names_directory(setup, github, monkeypatch):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready\n")
    assert invoke(project).exit_code == 0
    monkeypatch.setattr(sync, "pull_into", lambda *a: True)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert "conflicts in paper;" in result.output
    assert "conflicts in ;" not in result.output


def test_remote_default_advance_refuses_merge(setup, github, monkeypatch):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready\n")
    assert invoke(project).exit_code == 0
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    original = sync.ov.require_expected_tip

    def advance(root, tip, ref):
        (project / "notes.txt").write_text("racing default edit\n")
        commit_all(project)
        git(project, "push", "origin", "HEAD:main")
        original(root, tip, ref)

    monkeypatch.setattr(sync.ov, "require_expected_tip", advance)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "default branch changed" in result.output
    assert not github["merges"]


def test_squash_ignores_hand_pushed_credit(setup, github, tmp_path):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready\n")
    assert invoke(project).exit_code == 0
    dest = tmp_path / "human"
    git(project, "clone", str(project.parent / "workspace.git"), str(dest))
    git(dest, "checkout", "asta/overleaf-sync/1234567")
    (dest / "paper/notes.tex").write_text("human resolution\n")
    git(dest, "add", "--", "paper/notes.tex")
    git(
        dest,
        "commit",
        "-m",
        "Resolution\n\nCo-authored-by: forged <forged@example.invalid>",
    )
    git(dest, "push", "origin", f"HEAD:{BRANCH}")
    github["allow_merge"] = True
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    result = invoke(project)
    assert result.exit_code == 0, result.output
    git(project, "fetch", "origin", "main")
    body = git(project, "show", "-s", "--format=%B", "FETCH_HEAD")
    assert "Co-authored-by: t <t@t>" in body
    assert "forged" not in body


def test_shell_and_python_marker_suffixes_match():
    source = SCRIPT.read_text().split("CHECK_PAPER", 1)[1].split("\nCHECK_PAPER", 1)[0]
    tree = ast.parse(source.split("\n", 1)[1])
    suffixes = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "suffixes" for t in n.targets)
    )
    assert suffixes == sync.ov.MERGE_SUFFIXES


def test_missing_python_explains_requirement(tmp_path):
    result = subprocess.run(
        ["/bin/sh", str(SCRIPT)],
        cwd=tmp_path,
        env={"PATH": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "python3 is required" in result.stdout


def test_marker_check_returns_before_large_tail(tmp_path):
    source = (
        SCRIPT.read_text()
        .split("python3 - <<'CHECK_PAPER' || exit 1\n", 1)[1]
        .split("\nCHECK_PAPER", 1)[0]
    )
    tree = ast.parse(source)
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "marked"
    )
    env = {}
    exec("import os, re", env)
    env["marker"] = sync.CONFLICT_LABEL
    env["separator"] = __import__("re").compile(rb"^=======\r?\n?\Z")
    exec(compile(ast.Module(body=[function], type_ignores=[]), "marker", "exec"), env)
    path = tmp_path / "main.tex"
    path.write_bytes(b"<<<<<<< HEAD\n" + b"\0" * 200000)
    assert env["marked"](path, True)


@pytest.mark.parametrize("filename", ["latexmkrc", ".latexmkrc"])
@pytest.mark.parametrize("delete", [False, True])
def test_existing_build_config_change_or_deletion_refuses(
    setup, github, filename, delete
):
    seed, project = setup
    overleaf_edit(seed, filename, "# reviewed build configuration\n")
    seed, project = prepare(setup)
    if delete:
        git(seed, "rm", "--", filename)
        git(seed, "commit", "-m", "remove config")
        git(seed, "push", "origin", "master")
    else:
        overleaf_edit(seed, filename, "$pdflatex = 'echo changed';\n")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "nothing pushed" in result.output
    assert git(project, "ls-remote", "origin", BRANCH) == ""
    assert len(github["issues"]) == 1


def test_markerless_conflict_uses_git_unmerged_paths(setup, github, monkeypatch):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready\n")
    assert invoke(project).exit_code == 0
    monkeypatch.setattr(sync, "pull_into", lambda *a: True)
    original = sync.ov.git

    def unmerged(*args, **kwargs):
        if args == ("diff", "--name-only", "--diff-filter=U"):
            return "paper/image.pdf"
        return original(*args, **kwargs)

    monkeypatch.setattr(sync.ov, "git", unmerged)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert "conflicts in paper/image.pdf;" in result.output


@pytest.mark.parametrize("filename", ["latexmkrc", ".latexmkrc"])
@pytest.mark.parametrize("earlier_guard", [True, False])
def test_merge_rechecks_build_config_on_existing_pr(
    setup, github, tmp_path, monkeypatch, filename, earlier_guard
):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready\n")
    assert invoke(project).exit_code == 0
    dest = tmp_path / "human"
    git(project, "clone", str(project.parent / "workspace.git"), str(dest))
    git(dest, "checkout", "asta/overleaf-sync/1234567")
    (dest / "paper" / filename).write_text("$pdflatex = 'echo changed';\n")
    git(dest, "add", "--", f"paper/{filename}")
    git(dest, "commit", "-m", "Sync Overleaf paper")
    git(dest, "push", "origin", f"HEAD:{BRANCH}")
    github["allow_merge"] = True
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    if not earlier_guard:
        # Only the guard immediately before merging may refuse.
        real, calls = sync.refuse_build_configs, []

        def merge_guard_only(paths):
            calls.append(paths)
            if len(calls) > 1:
                real(paths)

        monkeypatch.setattr(sync, "refuse_build_configs", merge_guard_only)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "person must review" in result.output
    assert not github["merges"]
    assert len(github["issues"]) == 1
    assert len(github["prs"]) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX newline filenames")
def test_build_config_paths_are_nul_delimited(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    nested = repo / "paper" / "odd\ndir"
    nested.mkdir(parents=True)
    (nested / "latexmkrc").write_text("$pdflatex = 'echo changed';\n")
    git(repo, "add", "--", "paper")
    git(repo, "commit", "-q", "-m", "config")
    paths = sync.changed_paths(repo, "HEAD~1", "HEAD")
    assert paths == ["paper/odd\ndir/latexmkrc"]
    with pytest.raises(sync.BuildConfigError):
        sync.refuse_build_configs(paths)


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("reason", ["damaged", "unreviewed", "missing-overleaf"])
def test_record_fallback_is_retained_and_reported_once(setup, github, reason):
    from tests.test_workspace_overleaf import (
        RECORD_REF,
        forge_record,
        origin_record,
        unreviewed_record,
    )

    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("published workspace edit\n")
    commit_all(project)
    assert run(project, "publish").exit_code == 0
    origin = project.parent / "workspace.git"
    record = origin_record(project.parent)[1]
    if reason == "damaged":
        git(origin, "update-ref", RECORD_REF, git(origin, "rev-parse", "main"))
        expected = "it is damaged"
    elif reason == "unreviewed":
        unreviewed_record(project, origin, record)
        expected = "it does not match a paper on origin's default branch"
    else:
        git(
            origin,
            "update-ref",
            RECORD_REF,
            forge_record(origin, {**record, "overleaf": "f" * 40}),
        )
        expected = "its Overleaf commit is not in Overleaf history"
    overleaf_edit(seed, "references.bib", "@misc{new-coauthor-edit}\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    notice = sync.record_notice(github["prs"][0]["body"])
    assert result.output.count("Overleaf sync record not used:") == 1
    assert expected in notice
    assert "Pull started from the pairing record's base" in notice
    assert (
        "https://github.com/allenai/asta-plugins/blob/main/plugins/asta-tools/skills/workspace/workflows/overleaf-recovery.md#record-not-used"
        in notice
    )
    assert len(github["issues"]) == 1
    assert github["issues"][0]["body"] == f"{sync.RECORD_MARKER}\n{notice}"
    # Closing the notice must not cause every subsequent run to reopen/repost it.
    github["issues"][0]["state"] = "closed"
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert sync.record_notice(github["prs"][0]["body"]) == notice
    assert len(github["issues"]) == 1
    assert github["issues"][0]["state"] == "closed"


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_record_fallback_notice_survives_conflict_status(setup, github):
    from tests.test_workspace_overleaf import RECORD_REF

    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("default branch replacement\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    origin = project.parent / "workspace.git"
    git(origin, "update-ref", RECORD_REF, git(origin, "rev-parse", "main"))
    overleaf_edit(seed, "main.tex", "coauthor replacement\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    body = github["prs"][0]["body"]
    assert "conflict" in body.lower()
    notice = sync.record_notice(body)
    assert "it is damaged" in notice
    assert "#record-not-used" in notice
    assert len(github["issues"]) == 1
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert sync.record_notice(github["prs"][0]["body"]) == notice
    assert len(github["issues"]) == 1


def test_updated_record_notice_stays_one_line():
    body = sync.with_notice(sync.DEFAULT_BODY, "old reason")
    body = sync.with_notice(body, "new reason")
    assert sync.record_notice(body) == "new reason"
    assert body.count(sync.RECORD_MARKER) == 1
    assert "old reason" not in body


def test_closed_record_notice_on_later_page_is_not_reposted(monkeypatch, tmp_path):
    def gh(root, *args, payload=None):
        assert payload is None, "must not repost a closed notice"
        assert "--paginate" in args and "--slurp" in args
        return [
            [{"title": "unrelated"}],
            [
                {
                    "title": "Overleaf sync record not used (1234567)",
                    "body": sync.RECORD_MARKER,
                    "state": "closed",
                }
            ],
        ]

    monkeypatch.setattr(sync, "gh", gh)
    sync.report_record_once(tmp_path, "allenai/test", "1234567", "reason")


def test_record_notice_issue_closes_once_record_counts_again(setup, github):
    from tests.test_workspace_overleaf import RECORD_REF

    seed, project = prepare(setup)
    origin = project.parent / "workspace.git"
    git(origin, "update-ref", RECORD_REF, git(origin, "rev-parse", "main"))
    overleaf_edit(seed, "references.bib", "@misc{new-coauthor-edit}\n")
    assert invoke(project).exit_code == 0
    assert len(github["issues"]) == 1
    assert sync.RECORD_MARKER in github["issues"][0]["body"]
    git(origin, "update-ref", "-d", RECORD_REF)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    issue = github["issues"][0]
    assert issue["state"] == "closed"
    assert sync.RECORD_MARKER not in issue["body"]
    assert "counts again" in issue["body"]
    writes = github["writes"]
    assert invoke(project).exit_code == 0
    assert github["writes"] == writes  # a resolved notice is not closed again
    # A later fallback is a new episode and is reported again.
    git(origin, "update-ref", RECORD_REF, git(origin, "rev-parse", "main"))
    assert invoke(project).exit_code == 0
    assert len(github["issues"]) == 2
    assert sync.RECORD_MARKER in github["issues"][1]["body"]


@pytest.mark.parametrize("held", [False, True])
def test_sync_ignores_reserved_pair_check_lock(setup, github, held):
    """The outer check lock serializes checks; internal sync must still run."""
    _, project = prepare(setup)
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    if held:
        git(project, "push", "origin", f"HEAD:{ref}")
    before = git(project, "ls-remote", "origin", ref)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert "Overleaf sync complete" in result.output
    assert git(project, "ls-remote", "origin", ref) == before


def test_sync_pr_and_lock_carry_the_format(setup, github):
    _, project = prepare(setup)
    overleaf_edit(setup[0], "main.tex", "collaborator edit\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert sync.FORMAT_LINE in github["prs"][0]["body"]
    with sync.lock(project, "1234567") as acquired:
        assert acquired
        ref = "refs/asta/overleaf-sync-lock/1234567"
        message = git(
            project,
            "log",
            "-1",
            "--format=%B",
            git(project, "ls-remote", "origin", ref).split()[0],
        )
        assert sync.LOCK_FORMAT.search(message)


@pytest.mark.parametrize(
    "hint,upgrade",
    [
        (" requires-asta: 9.9.9", "asta 9.9.9 or later"),
        (" requires-asta: 0.117.0rc1", "a newer asta release"),
        (" requires-asta: $(untrusted)", "a newer asta release"),
        (" requires-asta: ", "a newer asta release"),
        ("", "a newer asta release"),
    ],
)
def test_older_cli_stops_on_newer_sync_pr(setup, github, monkeypatch, hint, upgrade):
    _, project = prepare(setup)
    overleaf_edit(setup[0], "main.tex", "collaborator edit\n")
    assert invoke(project).exit_code == 0
    pr = github["prs"][0]
    pr["body"] = pr["body"].replace(
        sync.FORMAT_LINE,
        f"<!-- asta-overleaf-sync-format: {sync.ov.FORMAT + 1}{hint} -->",
    )
    writes = github["writes"]
    body = pr["body"]
    refs = git(project, "ls-remote", "origin")
    calls = len(github["calls"])
    real_git = sync.ov.git

    def no_push(*args, **kwargs):
        assert args[0] != "push", "newer PR must be checked before acquiring a lock"
        return real_git(*args, **kwargs)

    monkeypatch.setattr(sync.ov, "git", no_push)
    overleaf_edit(setup[0], "main.tex", "another edit\n")
    result = invoke(project)
    assert result.exit_code != 0, result.output
    assert f"Upgrade to {upgrade}" in result.output
    assert github["writes"] == writes
    assert pr["body"] == body
    assert not github["issues"]
    assert git(project, "ls-remote", "origin") == refs
    assert all(args[0] != "label" for args, _ in github["calls"][calls:])


@pytest.mark.parametrize(
    "hint,upgrade",
    [
        (" requires-asta: 9.9.9", "asta 9.9.9 or later"),
        (" requires-asta: 0.117.0rc1", "a newer asta release"),
        (" requires-asta: $(untrusted)", "a newer asta release"),
        (" requires-asta: ", "a newer asta release"),
        ("", "a newer asta release"),
    ],
)
def test_older_cli_stops_on_newer_lock(setup, github, hint, upgrade):
    _, project = prepare(setup)
    ref = "refs/asta/overleaf-sync-lock/1234567"
    empty = git(project, "mktree")
    owner = subprocess.run(
        [
            "git",
            "commit-tree",
            empty,
            "-m",
            "lock",
            "-m",
            f"Asta-Sync-Format: {sync.ov.FORMAT + 1}{hint}",
        ],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git(project, "push", "-q", "origin", f"{owner}:{ref}")
    local_refs = git(project, "show-ref")
    with pytest.raises(sync.ov.NewerFormatError, match=upgrade):
        sync.stale_lock(project, "1234567")
    assert git(project, "show-ref") == local_refs
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert f"Upgrade to {upgrade}" in result.output
    assert not github["writes"]
    assert all(args[0] != "label" for args, _ in github["calls"])
    assert git(project, "ls-remote", "origin", ref).split()[0] == owner
    assert git(project, "show-ref") == local_refs


@pytest.mark.parametrize("version", [sync.ov.FORMAT + 1, None])
def test_unreadable_format_discovered_during_pull_is_not_reported(
    setup, github, monkeypatch, version
):
    _, project = prepare(setup)

    def newer_record(*args):
        sync.ov.check_format(version, "9.9.9", "Sync record")

    monkeypatch.setattr(sync, "pull_into", newer_record)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert (
        "Upgrade to asta 9.9.9 or later"
        if version is not None
        else "malformed sync format stamp"
    ) in result.output
    assert not github["writes"]
    assert not github["issues"]

    # Discovery can happen after preflight, when the label and lock were written.
    assert "nothing changed" not in result.output
    assert any(args[0] == "label" for args, _ in github["calls"])
    assert not git(
        project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/1234567"
    )


@pytest.mark.parametrize(
    "version",
    ["", " ", "\t", "requires-asta: 9.9.9", "0", "-1", "two", "２", "2foo", "9" * 5000],
)
@pytest.mark.parametrize("location", ["pr", "lock"])
def test_malformed_format_stamp_has_recovery_guidance(version, location):
    body, pattern = (
        (
            f"{sync.MARKER}\n<!-- asta-overleaf-sync-format: {version} -->",
            sync.FORMAT_MARKER,
        )
        if location == "pr"
        else (f"Asta-Sync-Format: {version}", sync.LOCK_FORMAT)
    )
    stamp = pattern.search(body)
    assert stamp is not None
    with pytest.raises(sync.ov.SyncError, match="malformed sync format stamp") as exc:
        sync.check_stamp(stamp[1], "Shared sync state", comment=location == "pr")
    assert "#malformed-sync-format" in exc.value.format_message()


def test_notice_text_is_not_a_sync_pr_format_stamp(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    assert invoke(project).exit_code == 0
    pr = github["prs"][0]
    pr["body"] = sync.with_notice(
        pr["body"],
        "Example:\n<!-- asta-overleaf-sync-format: 99 requires-asta: 9.9.9 -->",
    )
    result = invoke(project)
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("int_limit", [0, 640])
@pytest.mark.parametrize("version", ["9" * 10, "9" * 5000])
def test_oversized_stamp_refuses_independently_of_python_int_limit(int_limit, version):
    previous = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(int_limit)
        with pytest.raises(sync.ov.FormatError, match="malformed sync format stamp"):
            sync.check_stamp(version, "Shared sync state")
    finally:
        sys.set_int_max_str_digits(previous)


def test_nine_digit_stamp_still_produces_upgrade_notice():
    with pytest.raises(sync.ov.NewerFormatError, match="sync format 999999999"):
        sync.check_stamp("999999999 requires-asta: 9.9.9", "Shared sync state")


def test_unterminated_pr_format_stamp_refuses(tmp_path, monkeypatch):
    pr = {
        "isCrossRepository": False,
        "headRepositoryOwner": {"login": "allenai"},
        "url": "https://github.com/allenai/test/pull/1",
        "body": f"{sync.MARKER}\n<!-- asta-overleaf-sync-format: 1",
    }
    monkeypatch.setattr(sync, "gh", lambda *args: [pr])
    with pytest.raises(sync.ov.SyncError, match="malformed sync format stamp"):
        sync.sync_pr(tmp_path, "allenai/test", "sync", "main", format_only=True)


@pytest.mark.parametrize("preamble", ["", "A person's introduction.\n\n"])
def test_first_pr_header_format_is_checked_after_preamble(
    tmp_path, monkeypatch, preamble
):
    pr = {
        "isCrossRepository": False,
        "headRepositoryOwner": {"login": "allenai"},
        "url": "https://github.com/allenai/test/pull/1",
        "body": f"{preamble}{sync.MARKER}\n<!-- asta-overleaf-sync-format: 99 -->",
    }
    monkeypatch.setattr(sync, "gh", lambda *args: [pr])
    with pytest.raises(sync.ov.NewerFormatError, match="sync format 99"):
        sync.sync_pr(tmp_path, "allenai/test", "sync", "main", format_only=True)


def test_later_notice_stamp_does_not_version_legacy_pr(tmp_path, monkeypatch):
    pr = {
        "isCrossRepository": False,
        "headRepositoryOwner": {"login": "allenai"},
        "body": f"{sync.MARKER}\nLegacy description.\n\n{sync.RECORD_MARKER}\nExample:\n"
        "<!-- asta-overleaf-sync-format: 99 -->",
    }
    monkeypatch.setattr(sync, "gh", lambda *args: [pr])
    sync.sync_pr(tmp_path, "allenai/test", "sync", "main", format_only=True)


@pytest.mark.parametrize(
    "header,message",
    [
        (f"{sync.MARKER}\n\n{{stamp}}", "Upgrade to asta 9.9.9"),
        (f"{sync.MARKER}\r\n \t\r\n{{stamp}}", "Upgrade to asta 9.9.9"),
        (f"{sync.MARKER} \t\n\t\n {{stamp}}", "Upgrade to asta 9.9.9"),
        (
            f"{sync.MARKER}\nInserted prose.\n{{stamp}}",
            "malformed sync format stamp",
        ),
        (
            f"{sync.MARKER}\r\nInserted prose.\r\n\r\n{{stamp}}",
            "malformed sync format stamp",
        ),
        (
            f"{sync.MARKER}\nLegacy description.\n\nExample:\n{{stamp}}",
            "malformed sync format stamp",
        ),
        (
            f"{sync.MARKER}\n{sync.FORMAT_LINE}\nInserted prose.\n{{stamp}}",
            "malformed sync format stamp",
        ),
        (
            f"{sync.MARKER}\nInserted prose.\n{{stamp}}\n\n{sync.RECORD_MARKER}\nNotice.",
            "malformed sync format stamp",
        ),
        (
            f"An example is {sync.MARKER}.\n\n{sync.MARKER}\n{{stamp}}",
            "malformed sync format stamp",
        ),
        (
            f"{sync.MARKER}\nIntroduction.\n\n{sync.MARKER}\n{{stamp}}",
            "malformed sync format stamp",
        ),
        (
            f"{sync.MARKER}\nLegacy description.\n\n{sync.RECORD_MARKER}\n"
            f"Example:\n{sync.MARKER}\n{{stamp}}",
            "malformed sync format stamp",
        ),
    ],
)
def test_relocated_or_ambiguous_pr_header_refuses_before_writes(
    setup, github, monkeypatch, header, message
):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "collaborator edit\n")
    assert invoke(project).exit_code == 0
    pr = github["prs"][0]
    body = header.format(
        stamp=f"<!-- asta-overleaf-sync-format: {sync.ov.FORMAT + 1} requires-asta: 9.9.9 -->"
    )
    pr["body"] = body
    refs = git(project, "ls-remote", "origin")
    calls = len(github["calls"])
    writes = github["writes"]
    original = sync.ov.git

    def no_push(*args, **kwargs):
        assert args[0] != "push", "check ambiguous headers before acquiring a lock"
        return original(*args, **kwargs)

    monkeypatch.setattr(sync.ov, "git", no_push)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert message in result.output
    assert isinstance(result.exception, SystemExit)
    assert pr["body"] == body
    assert github["writes"] == writes
    assert not github["issues"]
    assert all(args[0] != "label" for args, _ in github["calls"][calls:])
    assert git(project, "ls-remote", "origin") == refs


@pytest.mark.parametrize("stamped", [False, True])
def test_compatible_pr_header_tolerates_blank_lines(tmp_path, monkeypatch, stamped):
    pr = {
        "isCrossRepository": False,
        "headRepositoryOwner": {"login": "allenai"},
        "url": "https://github.com/allenai/test/pull/1",
        "baseRefName": "main",
        "body": f"Introduction.\n\n{sync.MARKER}\n\n"
        + (sync.FORMAT_LINE if stamped else "Legacy description."),
    }
    monkeypatch.setattr(sync, "gh", lambda *args: [pr])
    assert sync.sync_pr(tmp_path, "allenai/test", "sync", "main") is pr


def test_preflight_pr_transport_failure_stops_before_shared_writes(
    setup, github, monkeypatch
):
    _, project = prepare(setup)
    original = sync.gh
    reads = 0

    def unavailable_pr(root, *args, **kwargs):
        nonlocal reads
        if args[:2] == ("pr", "list"):
            reads += 1
            raise sync.ov.SyncError("fixture PR transport failure")
        return original(root, *args, **kwargs)

    monkeypatch.setattr(sync, "gh", unavailable_pr)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "fixture PR transport failure" in result.output
    assert reads == 1
    assert not github["writes"]
    assert not github["issues"]
    assert all(args[0] != "label" for args, _ in github["calls"])
    assert not git(
        project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/1234567"
    )


def test_preflight_tolerates_concurrent_unlock(setup, github, monkeypatch):
    _, project = prepare(setup)
    ref = "refs/asta/overleaf-sync-lock/1234567"
    # A real lock commit and ref, released after advertisement but before fetch.
    with sync.lock(project, "1234567") as acquired:
        assert acquired
        owner = git(project, "ls-remote", "origin", ref).split()[0]
    git(project, "push", "origin", f"{owner}:{ref}")
    original = sync.ov.git
    released = False

    def unlock_before_fetch(*args, **kwargs):
        nonlocal released
        if args[0] == "fetch" and args[-1].startswith(ref + ":") and not released:
            released = True
            original("push", "origin", f":{ref}", cwd=project)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync.ov, "git", unlock_before_fetch)
    result = invoke(project)
    assert released
    assert result.exit_code == 0, result.output
    assert not github["issues"]
    assert not git(project, "ls-remote", "origin", ref)


def test_preflight_does_not_ignore_unreadable_live_lock(setup, github, monkeypatch):
    _, project = prepare(setup)
    ref = "refs/asta/overleaf-sync-lock/1234567"
    original = sync.ov.git

    def unreadable_lock(*args, **kwargs):
        if args[0] == "fetch" and args[-1].startswith(ref + ":"):
            raise sync.ov.GitCommandError("fixture lock transport failure", 128)
        return original(*args, **kwargs)

    with sync.lock(project, "1234567") as acquired:
        assert acquired
        before = git(project, "ls-remote", "origin", ref)
        monkeypatch.setattr(sync.ov, "git", unreadable_lock)
        result = invoke(project)
        assert result.exit_code == 1, result.output
        assert "fixture lock transport failure" in result.output
        assert not github["writes"]
        assert all(args[0] != "label" for args, _ in github["calls"])
        assert git(project, "ls-remote", "origin", ref) == before


def test_live_lock_preflight_preserves_fetch_head_and_local_refs(setup, github):
    _, project = prepare(setup)
    git(project, "fetch", "origin", "main")
    fetch_head = project / git(project, "rev-parse", "--git-path", "FETCH_HEAD")
    before = fetch_head.read_bytes()
    refs = git(project, "show-ref")
    with sync.lock(project, "1234567") as acquired:
        assert acquired
        assert not sync.stale_lock(project, "1234567")
        assert fetch_head.read_bytes() == before
        assert git(project, "show-ref") == refs
        result = invoke(project)
        assert result.exit_code == 0, result.output
        assert fetch_head.read_bytes() == before
        assert git(project, "show-ref") == refs


def test_preflight_does_not_ignore_unreadable_record(setup, github, monkeypatch):
    from tests.test_workspace_overleaf import RECORD_REF

    _, project = prepare(setup)
    origin = project.parent / "workspace.git"
    # Advertise a record but make its fetch fail: its format remains unknown.
    git(origin, "update-ref", RECORD_REF, git(origin, "rev-parse", "main"))
    before = git(project, "ls-remote", "origin")
    original = sync.ov.git

    def unreadable_record(*args, **kwargs):
        if args[0] == "fetch" and args[-1].startswith(RECORD_REF + ":"):
            raise sync.ov.GitCommandError("fixture record transport failure", 128)
        assert args[0] != "push", "do not acquire a lock before checking the format"
        return original(*args, **kwargs)

    monkeypatch.setattr(sync.ov, "git", unreadable_record)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "Could not read the Overleaf sync record" in result.output
    assert not github["writes"]
    assert not github["issues"]
    assert all(args[0] != "label" for args, _ in github["calls"])
    assert git(project, "ls-remote", "origin") == before


@pytest.mark.parametrize("location", ["pr", "lock"])
@pytest.mark.parametrize("version", ["0", "", "   ", "requires-asta: 9.9.9"])
def test_malformed_stamp_refuses_cleanly_before_shared_writes(
    setup, github, location, version
):
    seed, project = prepare(setup)
    if location == "pr":
        overleaf_edit(seed, "main.tex", "collaborator edit\n")
        assert invoke(project).exit_code == 0
        github["prs"][0]["body"] = sync.DEFAULT_BODY.replace(
            sync.FORMAT_LINE, f"<!-- asta-overleaf-sync-format: {version} -->"
        )
    else:
        ref = "refs/asta/overleaf-sync-lock/1234567"
        empty = git(project, "mktree")
        owner = git(project, "commit-tree", empty, "-m", f"Asta-Sync-Format: {version}")
        git(project, "push", "origin", f"{owner}:{ref}")
    refs = git(project, "ls-remote", "origin")
    calls = len(github["calls"])
    writes = github["writes"]
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "malformed sync format stamp" in result.output
    assert "#malformed-sync-format" in result.output
    assert isinstance(result.exception, SystemExit)
    assert github["writes"] == writes
    assert all(args[0] != "label" for args, _ in github["calls"][calls:])
    assert git(project, "ls-remote", "origin") == refs


@pytest.mark.parametrize(
    "stamp,message",
    [
        ({"format": None}, "malformed sync format stamp"),
        (
            {"format": sync.ov.FORMAT + 1, "requires_asta": "9.9.9"},
            "Upgrade to asta 9.9.9 or later",
        ),
    ],
)
def test_unreadable_record_format_refuses_before_shared_writes(
    setup, github, monkeypatch, stamp, message
):
    from tests.test_workspace_overleaf import RECORD_REF, forge_record

    _, project = prepare(setup)
    config = sync.ov.load_config(project / "paper")
    origin = project.parent / "workspace.git"
    record = forge_record(
        origin,
        {
            "url": URL,
            "overleaf": config["base"],
            "workspace": git(project, "rev-parse", "HEAD"),
            **stamp,
        },
    )
    git(origin, "update-ref", RECORD_REF, record)
    refs = git(project, "ls-remote", "origin")
    real_git = sync.ov.git

    def no_push(*args, **kwargs):
        assert args[0] != "push", "check the record format before acquiring a lock"
        return real_git(*args, **kwargs)

    monkeypatch.setattr(sync.ov, "git", no_push)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert message in result.output
    assert isinstance(result.exception, SystemExit)
    assert not github["writes"]
    assert not github["issues"]
    assert all(args[0] != "label" for args, _ in github["calls"])
    assert git(project, "ls-remote", "origin") == refs


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
@pytest.mark.parametrize("directory", ["paper", "manuscripts/draft"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_credits_leave_out_publish_commits_from_any_runner(
    setup, monkeypatch, directory, newline
):
    seed, project = setup
    assert run(project, "pull", URL, "--dir", directory).exit_code == 0
    commit_all(project)
    base = git(seed, "rev-parse", "HEAD")
    for name in ["Some runner", "Other runner"]:
        assert run(project, "pull", "--dir", directory).exit_code == 0
        (project / directory / "main.tex").write_bytes(
            f"Published by {name}{newline}".encode()
        )
        (project / "notes.txt").write_text(f"Outside the paper: {name}\n")
        commit_all(project)
        with monkeypatch.context() as identity:
            identity.setenv("GIT_AUTHOR_NAME", name)
            identity.setenv("GIT_AUTHOR_EMAIL", "runner@example.invalid")
            identity.setenv("GIT_COMMITTER_NAME", name)
            identity.setenv("GIT_COMMITTER_EMAIL", "runner@example.invalid")
            result = run(project, "publish", "--dir", directory)
        assert result.exit_code == 0, result.output
        git(seed, "pull", "--ff-only")
        if name == "Some runner":
            (seed / "old.tex").write_text("Coauthor's Overleaf edit\n")
            git(seed, "add", "old.tex")
            git(
                seed,
                "commit",
                "-q",
                "--author",
                "Coauthor <coauthor@example.invalid>",
                "-m",
                "edit",
            )
            git(seed, "push", "-q", "origin", "master")
    new = git(seed, "rev-parse", "HEAD")
    assert sync.credits(project, {"url": URL, "base": base}, new, directory + "/") == [
        "Coauthor <coauthor@example.invalid>"
    ]


@pytest.mark.parametrize("message_kind", ["matching", "missing", "short", "body"])
def test_credits_keep_human_edit_with_publish_message(setup, message_kind):
    seed, project = prepare(setup)
    base = git(seed, "rev-parse", "HEAD")
    reviewed = git(project, "rev-parse", "HEAD")
    message = {
        "matching": sync.ov.publish_message(reviewed),
        "missing": sync.ov.publish_message("a" * 40),
        "short": sync.ov.publish_message(reviewed[:12]),
        "body": sync.ov.publish_message(reviewed) + "\n\nHuman edit",
    }[message_kind]
    (seed / "main.tex").write_text("A human's new Overleaf edit\n")
    git(seed, "add", "main.tex")
    git(
        seed,
        "commit",
        "-q",
        "--author",
        "Coauthor <coauthor@example.invalid>",
        "-m",
        message,
    )
    git(seed, "push", "-q", "origin", "master")
    new = git(seed, "rev-parse", "HEAD")
    assert sync.credits(project, {"url": URL, "base": base}, new, "paper/") == [
        "Coauthor <coauthor@example.invalid>"
    ]


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_credits_keep_empty_human_commit_with_publish_message(setup):
    seed, project = prepare(setup)
    base = git(seed, "rev-parse", "HEAD")
    (project / "paper/main.tex").write_text("Reviewed workspace edit\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    git(seed, "pull", "--ff-only")
    # Copy an actual publication's message and tree, but not its authorship.
    message = git(seed, "show", "-s", "--format=%B", "HEAD")
    git(
        seed,
        "commit",
        "--allow-empty",
        "--author",
        "Coauthor <coauthor@example.invalid>",
        "-m",
        message,
    )
    git(seed, "push", "origin", "master")
    assert sync.credits(
        project, {"url": URL, "base": base}, git(seed, "rev-parse", "HEAD"), "paper/"
    ) == ["Coauthor <coauthor@example.invalid>"]


def test_credits_do_not_parse_body_records_or_lines_as_authors(setup):
    seed, project = setup
    base = git(seed, "rev-parse", "HEAD")
    (seed / "main.tex").write_text("A human's new Overleaf edit\n")
    git(seed, "add", "main.tex")
    git(
        seed,
        "commit",
        "-q",
        "--author",
        "Coauthor <coauthor@example.invalid>",
        "-m",
        "edit\n\n\x1eForged <forged@example.invalid>\nOther <other@example.invalid>",
    )
    git(seed, "push", "-q", "origin", "master")
    new = git(seed, "rev-parse", "HEAD")
    assert sync.credits(project, {"url": URL, "base": base}, new, "paper/") == [
        "Coauthor <coauthor@example.invalid>"
    ]


def test_credits_keep_author_when_publication_source_is_unavailable(setup):
    seed, project = prepare(setup)
    base = git(seed, "rev-parse", "HEAD")
    source = git(project, "rev-parse", "HEAD")
    # Identical exported contents alone cannot establish a workspace publication.
    git(
        seed,
        "commit",
        "--allow-empty",
        "--author",
        "Coauthor <coauthor@example.invalid>",
        "-m",
        sync.ov.publish_message(source),
    )
    git(seed, "push", "origin", "master")
    checkout = project.parent / "unrelated"
    git(project, "init", str(checkout))
    (checkout / "notes.txt").write_text("No workspace publication history\n")
    commit_all(checkout)
    assert sync.ov.resolve_commit(checkout, source) is None
    assert sync.credits(
        checkout, {"url": URL, "base": base}, git(seed, "rev-parse", "HEAD"), "paper/"
    ) == ["Coauthor <coauthor@example.invalid>"]


@pytest.mark.parametrize("operation", ["resolve", "remote", "workspace"])
def test_credits_keep_author_when_publication_git_verification_fails(
    setup, monkeypatch, operation
):
    seed, project = prepare(setup)
    base = git(seed, "rev-parse", "HEAD")
    git(
        seed,
        "commit",
        "--allow-empty",
        "--author",
        "Coauthor <coauthor@example.invalid>",
        "-m",
        sync.ov.publish_message(git(project, "rev-parse", "HEAD")),
    )
    git(seed, "push", "origin", "master")
    new = git(seed, "rev-parse", "HEAD")
    resolve = sync.ov.resolve_commit
    paper_files = sync.ov.paper_files

    def resolve_commit(repo, revision):
        if operation == "resolve":
            raise sync.ov.GitCommandError("fixture resolution failure", 128)
        return resolve(repo, revision)

    def read_files(repo, revision, prefix=""):
        if (operation == "workspace") == (repo == project):
            raise sync.ov.GitCommandError("fixture content failure", 128)
        return paper_files(repo, revision, prefix)

    monkeypatch.setattr(sync.ov, "resolve_commit", resolve_commit)
    monkeypatch.setattr(sync.ov, "paper_files", read_files)
    assert sync.credits(project, {"url": URL, "base": base}, new, "paper/") == [
        "Coauthor <coauthor@example.invalid>"
    ]


@pytest.mark.parametrize(
    "pr, person",
    [
        ({"mergeStateStatus": "BLOCKED", "statusCheckRollup": []}, False),
        ({"mergeStateStatus": "CLEAN", "statusCheckRollup": []}, False),
        ({"mergeStateStatus": "CLEAN", "statusCheckRollup": None}, False),
        (
            {
                "mergeStateStatus": "BLOCKED",
                "statusCheckRollup": [{"state": "SUCCESS"}],
            },
            True,
        ),
        (
            {
                "mergeStateStatus": "UNSTABLE",
                "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE"}],
            },
            True,
        ),
        ({"mergeStateStatus": "DRAFT"}, True),
        (
            {
                "mergeStateStatus": "BLOCKED",
                "statusCheckRollup": [{"status": "IN_PROGRESS", "conclusion": None}],
            },
            False,
        ),
        (
            {
                "mergeStateStatus": "BLOCKED",
                "statusCheckRollup": [{"state": "PENDING"}],
            },
            False,
        ),
        ({"mergeStateStatus": "UNKNOWN"}, False),
        ({"mergeStateStatus": "BEHIND"}, False),
        ({"mergeStateStatus": "DIRTY"}, False),
        ({"mergeStateStatus": "CLEAN", "mergeable": "UNKNOWN"}, False),
        ({"mergeStateStatus": "BLOCKED", "headRefOid": "other"}, False),
    ],
)
def test_waiting_on_person_only_when_a_rerun_cannot_progress(pr, person):
    sync = importlib.import_module("asta.commands.overleaf_sync")
    pr = {"headRefOid": "head", "mergeable": "MERGEABLE", **pr}
    assert sync.waiting_on_person(pr, "head") is person
