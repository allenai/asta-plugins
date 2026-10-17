"""The live-check orchestration runs offline over real Git and fake GitHub checks."""

import importlib
from contextlib import contextmanager

import click
import pytest
from click.testing import CliRunner

from asta.cli import cli
from tests.test_overleaf_sync import github as github  # noqa: F401
from tests.test_overleaf_sync import prepare
from tests.test_workspace_overleaf import git
from tests.test_workspace_overleaf import setup as setup  # noqa: F401

check = importlib.import_module("asta.commands.overleaf_check")


@pytest.fixture
def scratch(setup, github, monkeypatch):
    _, project = prepare(setup)
    github["allow_merge"] = True
    for name in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)
    original = check.sync.gh
    waits = []

    def gh(root, *args, payload=None):
        # The existing fake merges into this fixture's local workspace remote.
        if args[0] == "api" and "/pulls/" in args[1] and payload == {"state": "closed"}:
            github["prs"].clear()
            return None
        result = original(project, *args, payload=payload)
        for pr in github["prs"]:
            pr["statusCheckRollup"] = [{"status": "COMPLETED", "conclusion": "SUCCESS"}]
        return result

    monkeypatch.setattr(check.sync, "gh", gh)
    monkeypatch.setattr(check.time, "sleep", lambda seconds: waits.append(seconds))
    baseline = check.ov.paper_files(project, "HEAD", "paper/")
    head = git(project, "rev-parse", "HEAD")
    return project, baseline, head, waits


def invoke(project, *args):
    return CliRunner().invoke(
        cli, ["workspace", "overleaf", "check", "--project", str(project), *args]
    )


def assert_restored(scratch):
    project, baseline, head, _ = scratch
    assert git(project, "rev-parse", "HEAD") == head
    assert git(project, "status", "--porcelain") == ""
    git(project, "fetch", "origin", "main")
    assert check.ov.paper_files(project, "FETCH_HEAD", "paper/") == baseline
    seed = project.parent / "seed"
    git(seed, "fetch", "origin", "master")
    assert check.ov.paper_files(seed, "FETCH_HEAD") == baseline
    assert not git(project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/*")
    assert not git(project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/*")


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_complete_round_trip_merges_twice_publishes_and_restores(scratch, github):
    project, _, _, _ = scratch
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert "live check PASS" in result.output
    assert len(github["merges"]) == 2
    assert not github["prs"]
    assert_restored(scratch)
    # Restoration leaves a valid paired state for the next release check.
    git(project, "reset", "--hard", "FETCH_HEAD")
    assert invoke(project).exit_code == 0


def test_waits_for_checks_inside_the_call(scratch, github, monkeypatch):
    project, _, _, waits = scratch
    original = check.sync.gh
    pending = [True]

    def delayed(root, *args, payload=None):
        result = original(root, *args, payload=payload)
        if pending[0]:
            for pr in github["prs"]:
                pr["statusCheckRollup"] = [
                    {"status": "IN_PROGRESS", "conclusion": None}
                ]
        return result

    def sleep(seconds):
        waits.append(seconds)
        pending[0] = False

    monkeypatch.setattr(check.sync, "gh", delayed)
    monkeypatch.setattr(check.time, "sleep", sleep)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert waits and len(github["merges"]) == 2
    assert_restored(scratch)


def test_failure_after_opening_pr_restores_both_and_closes_it(
    scratch, github, monkeypatch
):
    project, _, _, _ = scratch
    original = check.RoundTrip.run_sync

    def fail(trial):
        original(trial)
        raise check.ov.SyncError("Injected failure after a scratch write")

    monkeypatch.setattr(check.RoundTrip, "run_sync", fail)
    result = invoke(project)
    assert result.exit_code != 0
    assert "Injected failure" in result.output
    assert "live check PASS" not in result.output
    assert not github["prs"]
    assert_restored(scratch)


def test_wait_timeout_restores_instead_of_leaving_a_pending_check(
    scratch, github, monkeypatch
):
    project, _, _, _ = scratch
    original = check.sync.gh

    def pending(root, *args, payload=None):
        result = original(root, *args, payload=payload)
        for pr in github["prs"]:
            pr["statusCheckRollup"] = []
        return result

    monkeypatch.setattr(check.sync, "gh", pending)
    monkeypatch.setattr(
        check.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(
            check.ov.SyncError("Live check timed out")
        ),
    )
    result = invoke(project, "--timeout", "30")
    assert result.exit_code != 0
    assert "timed out" in result.output
    assert not github["prs"]
    assert_restored(scratch)


def test_failed_pr_checks_fail_and_restore_without_merging(
    scratch, github, monkeypatch
):
    project, _, _, _ = scratch
    original = check.sync.gh

    def failed(root, *args, payload=None):
        result = original(root, *args, payload=payload)
        for pr in github["prs"]:
            pr["statusCheckRollup"] = [{"status": "COMPLETED", "conclusion": "FAILURE"}]
        return result

    monkeypatch.setattr(check.sync, "gh", failed)
    result = invoke(project)
    assert result.exit_code != 0
    assert "scratch PR check failed" in result.output
    assert "Overleaf live check FAIL" in result.output
    assert not github["merges"] and not github["prs"]
    assert_restored(scratch)


def test_check_detects_matching_but_clobbered_papers_and_restores(scratch, monkeypatch):
    project, _, _, _ = scratch
    original = check.RoundTrip.merge_and_wait

    def clobber(trial):
        original(trial)
        (trial.paper / "main.tex").write_bytes(b"clobbered by a broken release\n")
        trial.commit(
            trial.work, "Broken release clobbered a paper", [trial.prefix + "main.tex"]
        )
        git(trial.work, "push", "origin", f"HEAD:refs/heads/{trial.default}")
        click.get_current_context().invoke(
            check.ov.publish,
            project=trial.work,
            directory=trial.directory,
            dry_run=False,
            expected_commit=None,
        )

    monkeypatch.setattr(check.RoundTrip, "merge_and_wait", clobber)
    result = invoke(project)
    assert result.exit_code != 0
    assert "co-author merge workspace" in result.output
    assert "Overleaf live check FAIL" in result.output
    assert_restored(scratch)


def test_refuses_differing_pair_without_changing_it(scratch, github):
    project, _, _, _ = scratch
    seed = project.parent / "seed"
    from tests.test_workspace_overleaf import overleaf_edit

    overleaf_edit(seed, "main.tex", "an edit already waiting\n")
    # A differing pair is rejected before trying to claim or alter its PR.
    result = invoke(project)
    assert result.exit_code != 0
    assert "identical" in result.output
    assert git(seed, "show", "HEAD:main.tex") == "an edit already waiting"
    assert not github["calls"] or not github["merges"]


def test_refuses_reserved_overleaf_source_without_deleting_it(scratch):
    project, _, _, _ = scratch
    seed = project.parent / "seed"
    from tests.test_workspace_overleaf import overleaf_edit

    overleaf_edit(seed, "overleaf.json", "an original Overleaf source\n")
    result = invoke(project)
    assert result.exit_code != 0
    assert "reserved overleaf.json filename" in result.output
    assert git(seed, "show", "HEAD:overleaf.json") == "an original Overleaf source"


def test_refuses_unrelated_reserved_branch_without_writes(scratch):
    project, _, head, _ = scratch
    ref = "refs/heads/asta/overleaf-sync/1234567"
    (project / "references.bib").write_text("unrelated branch work\n")
    git(project, "add", "references.bib")
    git(project, "commit", "-m", "Other workspace work")
    git(project, "push", "origin", f"HEAD:{ref}")
    git(project, "reset", "--hard", head)
    result = invoke(project)
    assert result.exit_code != 0
    assert "reserved sync branch has unrelated work" in result.output
    assert git(project, "ls-remote", "origin", ref)
    git(project, "push", "origin", f":{ref}")
    assert_restored(scratch)


def test_preserves_a_leftover_sync_created_branch(scratch):
    project, _, head, _ = scratch
    ref = "refs/heads/asta/overleaf-sync/1234567"
    git(project, "commit", "--allow-empty", "-m", "Sync Overleaf paper")
    old_branch = git(project, "rev-parse", "HEAD")
    git(project, "push", "origin", f"HEAD:{ref}")
    git(project, "reset", "--hard", head)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert git(project, "ls-remote", "origin", ref).split()[0] == old_branch
    git(project, "push", "origin", f":{ref}")
    assert_restored(scratch)


@pytest.mark.parametrize("name", ["CI", "GITHUB_ACTIONS"])
def test_never_runs_live_check_in_ci(scratch, monkeypatch, name):
    project, _, _, _ = scratch
    monkeypatch.setenv(name, "true")
    result = invoke(project)
    assert result.exit_code != 0
    assert "outside CI" in result.output
    assert_restored(scratch)


def test_refuses_held_check_lock(scratch):
    project, _, _, _ = scratch
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    git(project, "push", "origin", f"HEAD:{ref}")
    result = invoke(project)
    assert result.exit_code != 0
    assert "Another live check" in result.output
    assert git(project, "ls-remote", "origin", ref)
    git(project, "push", "origin", f":{ref}")
    assert_restored(scratch)


def test_regular_sync_refuses_pair_owned_by_check(scratch):
    project, _, _, _ = scratch
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    git(project, "push", "origin", f"HEAD:{ref}")
    result = CliRunner().invoke(
        cli, ["workspace", "overleaf", "sync", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "live release check owns" in result.output
    git(project, "push", "origin", f":{ref}")


def test_sync_rechecks_check_lock_after_acquiring_normal_lock(scratch, monkeypatch):
    project, _, _, _ = scratch
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    original = check.sync.lock

    @contextmanager
    def lock(root, project_id):
        with original(root, project_id) as acquired:
            git(project, "push", "origin", f"HEAD:{ref}")
            yield acquired

    monkeypatch.setattr(check.sync, "lock", lock)
    result = CliRunner().invoke(
        cli, ["workspace", "overleaf", "sync", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "live release check owns" in result.output
    git(project, "push", "origin", f":{ref}")
    assert_restored(scratch)


def test_check_rechecks_normal_sync_lock_after_preflight(scratch, monkeypatch):
    project, _, _, _ = scratch
    ref = "refs/asta/overleaf-sync-lock/1234567"
    original = check.sync.lock

    @contextmanager
    def lock(root, project_id):
        with original(root, project_id) as acquired:
            git(project, "push", "origin", f"HEAD:{ref}")
            yield acquired

    monkeypatch.setattr(check.sync, "lock", lock)
    result = invoke(project)
    assert result.exit_code != 0
    assert "acquired its lock during preflight" in result.output
    assert git(project, "ls-remote", "origin", ref)
    git(project, "push", "origin", f":{ref}")
    assert_restored(scratch)


def test_cleanup_error_never_reports_pass(scratch, monkeypatch):
    project, _, _, _ = scratch
    original = check.RoundTrip.restore

    def fail(trial):
        original(trial)
        raise check.ov.SyncError("Injected cleanup failure")

    monkeypatch.setattr(check.RoundTrip, "restore", fail)
    result = invoke(project)
    assert result.exit_code != 0
    assert "Injected cleanup failure" in result.output
    assert "live check PASS" not in result.output
    assert_restored(scratch)


def test_pr_close_failure_still_restores_both_contents(scratch, github, monkeypatch):
    project, _, _, _ = scratch
    original_sync = check.RoundTrip.run_sync

    def fail_sync(trial):
        original_sync(trial)
        raise check.ov.SyncError("Injected check failure")

    def fail_close(trial):
        raise check.ov.SyncError("Injected GitHub outage")

    monkeypatch.setattr(check.RoundTrip, "run_sync", fail_sync)
    monkeypatch.setattr(check.RoundTrip, "close_pr", fail_close)
    result = invoke(project)
    assert result.exit_code != 0
    assert "closing the check PR" in result.output
    assert "Scratch restoration failed" in result.output
    assert "live check PASS" not in result.output
    assert_restored(scratch)


def test_alarm_is_a_real_deadline():
    with pytest.raises(check.CheckTimeout, match="timed out"):
        with check.deadline(1):
            check.signal.pause()
