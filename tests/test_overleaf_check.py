"""The live-check orchestration runs offline over real Git and fake GitHub checks."""

import importlib
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

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


def assert_clean(scratch):
    """A passing check leaves the pair in sync with no PR, lock or conflict markers."""
    project, _, _, _ = scratch
    git(project, "fetch", "origin", "main")
    workspace = check.ov.paper_files(project, "FETCH_HEAD", "paper/")
    seed = project.parent / "seed"
    git(seed, "fetch", "origin", "master")
    assert check.ov.paper_files(seed, "FETCH_HEAD") == workspace
    assert b"<<<<<<<" not in workspace[check.CHECK_FILE]
    assert not git(project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/*")


def assert_failed_state(scratch, github):
    """Failures retain the co-author edit and PR for inspection, without merging."""
    project, baseline, _, _ = scratch
    git(project, "fetch", "origin", "main")
    assert check.ov.paper_files(project, "FETCH_HEAD", "paper/") == baseline
    seed = project.parent / "seed"
    git(seed, "fetch", "origin", "master")
    files = check.ov.paper_files(seed, "FETCH_HEAD")
    assert files.keys() == baseline.keys() | {check.CHECK_FILE}
    assert b"co-author" in files[check.CHECK_FILE]
    assert not github["merges"]
    assert len(github["prs"]) == 1
    assert not git(project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/*")


def assert_unchanged(scratch, refs):
    project, baseline, _, _ = scratch
    assert git(project, "ls-remote", "origin") == refs
    seed = project.parent / "seed"
    git(seed, "fetch", "origin", "master")
    assert check.ov.paper_files(seed, "FETCH_HEAD") == baseline
    assert check.ov.paper_files(project, "HEAD", "paper/") == baseline


def stale_check_lock(project):
    tree = check.ov.git("mktree", cwd=project, input=b"")
    owner = check.ov.git(
        "commit-tree",
        tree,
        cwd=project,
        env={**os.environ, "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"},
        input=b"Dead check\n",
    )
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    git(project, "push", "origin", f"{owner}:{ref}")


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_complete_round_trip_merges_twice_publishes(scratch, github):
    project, _, _, _ = scratch
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert "live check PASS" in result.output
    assert len(github["merges"]) == 2
    assert not github["prs"]
    assert_clean(scratch)
    # A successful check leaves a valid paired state for the next check.
    git(project, "reset", "--hard", "FETCH_HEAD")
    assert invoke(project).exit_code == 0


@pytest.mark.parametrize("waiting_state", ["CLEAN", "BLOCKED", "UNKNOWN"])
def test_waits_for_checks_inside_the_call(scratch, github, monkeypatch, waiting_state):
    project, _, _, waits = scratch
    original = check.sync.gh
    pending = [True]

    def delayed(root, *args, payload=None):
        result = original(root, *args, payload=payload)
        for pr in github["prs"]:
            pr["mergeStateStatus"] = waiting_state if pending[0] else "CLEAN"
            pr["mergeable"] = "UNKNOWN" if pending[0] else "MERGEABLE"
            if pending[0]:
                pr["statusCheckRollup"] = [
                    {"status": "IN_PROGRESS", "conclusion": None}
                ]
        return result

    sync_calls = []
    original_sync = check.RoundTrip.run_sync

    def run_sync(trial):
        sync_calls.append(pending[0])
        original_sync(trial)

    def sleep(seconds):
        # The opening sync was the only sync while checks remained pending.
        assert sync_calls == [True]
        waits.append(seconds)
        pending[0] = False

    monkeypatch.setattr(check.RoundTrip, "run_sync", run_sync)
    monkeypatch.setattr(check.sync, "gh", delayed)
    monkeypatch.setattr(check.time, "sleep", sleep)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert waits and len(github["merges"]) == 2
    assert_clean(scratch)


def test_failed_pr_checks_fail_without_merging(scratch, github, monkeypatch):
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
    assert_failed_state(scratch, github)


def test_normalizes_a_relative_paper_directory(scratch):
    project, _, _, _ = scratch
    result = invoke(project, "--dir", "./paper")
    assert result.exit_code == 0, result.output
    assert_clean(scratch)


@pytest.mark.parametrize("name", ["CI", "GITHUB_ACTIONS"])
def test_never_runs_live_check_in_ci(scratch, monkeypatch, name):
    project, _, _, _ = scratch
    refs = git(project, "ls-remote", "origin")
    monkeypatch.setenv(name, "true")
    result = invoke(project)
    assert result.exit_code != 0
    assert "outside CI" in result.output
    assert_unchanged(scratch, refs)


def test_alarm_is_a_real_deadline():
    with pytest.raises(check.CheckTimeout, match="timed out"):
        with check.deadline(1):
            check.signal.pause()


@pytest.mark.parametrize(
    "url",
    ["https://git.overleaf.com/1234567/", "https://git@git.overleaf.com/1234567.git/"],
)
def test_url_variants_use_the_sync_lock_and_branch(scratch, monkeypatch, url):
    project, _, _, _ = scratch
    # load_config already normalizes supported URL variants; retain that contract.
    import json

    for repo in (project,):
        path = repo / "paper/overleaf.json"
        config = json.loads(path.read_text())
        path.write_text(json.dumps(dict(config, url=url)) + "\n")
        git(repo, "add", "paper/overleaf.json")
        git(repo, "commit", "-m", "Pair URL spelling")
        git(repo, "push", "origin", "HEAD:main")
    held = "refs/asta/overleaf-sync-lock/check-1234567"
    git(project, "push", "origin", f"HEAD:{held}")
    result = invoke(project)
    assert result.exit_code != 0
    assert "pair busy" in result.output
    assert git(project, "ls-remote", "origin", held)
    git(project, "push", "origin", f":{held}")
    assert not git(project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/*")


@pytest.mark.parametrize(
    "conclusion",
    ["STALE", "STARTUP_FAILURE", "TIMED_OUT", "CANCELLED", "UNKNOWN", None],
)
def test_every_unsuccessful_terminal_check_fails_without_waiting(
    scratch, github, monkeypatch, conclusion
):
    project, _, _, waits = scratch
    original = check.sync.gh

    def failed(root, *args, payload=None):
        result = original(root, *args, payload=payload)
        for pr in github["prs"]:
            pr["statusCheckRollup"] = [
                {"status": "COMPLETED", "conclusion": conclusion}
            ]
        return result

    monkeypatch.setattr(check.sync, "gh", failed)
    result = invoke(project)
    assert result.exit_code != 0
    assert (
        "release step" in result.output and "scratch PR check failed" in result.output
    )
    assert not waits
    assert_failed_state(scratch, github)


@pytest.mark.parametrize("reason", ["no checks", "review", "rules", "skipped only"])
def test_unattended_merge_setup_failure_is_actionable(
    scratch, github, monkeypatch, reason
):
    project, _, _, waits = scratch
    original = check.sync.gh
    clock = [0]
    monkeypatch.setattr(check.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    def blocked(root, *args, payload=None):
        result = original(root, *args, payload=payload)
        for pr in github["prs"]:
            if reason == "no checks":
                pr["statusCheckRollup"] = []
            elif reason == "review":
                pr["reviewDecision"] = "REVIEW_REQUIRED"
            elif reason == "rules":
                pr["mergeStateStatus"] = "BLOCKED"
            else:
                pr["statusCheckRollup"] = [
                    {"status": "COMPLETED", "conclusion": "SKIPPED"}
                ]
        return result

    monkeypatch.setattr(check.sync, "gh", blocked)
    monkeypatch.setattr(check.time, "sleep", sleep)
    result = invoke(project)
    assert result.exit_code != 0
    assert "pair access/setup" in result.output
    assert_failed_state(scratch, github)
    if reason == "no checks":
        assert sum(waits) == check.CHECK_DISCOVERY_SECONDS


def test_initial_empty_rollup_can_discover_checks(scratch, github, monkeypatch):
    project, _, _, waits = scratch
    original = check.sync.gh

    def delayed(root, *args, payload=None):
        result = original(root, *args, payload=payload)
        if not waits:
            for pr in github["prs"]:
                pr["statusCheckRollup"] = []
        return result

    monkeypatch.setattr(check.sync, "gh", delayed)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert waits == [5]
    assert len(github["merges"]) == 2
    assert_clean(scratch)


def test_main_thread_requirement_is_a_clear_error():
    def run():
        with check.deadline(1):
            pytest.fail("worker thread must be refused before starting")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(check.ov.SyncError, match="main thread"):
            pool.submit(run).result()


@pytest.mark.parametrize(
    "field,state,phase",
    [
        ("mergeable", "CONFLICTING", "release step"),
        ("mergeStateStatus", "DIRTY", "release step"),
        ("mergeStateStatus", "BEHIND", "release step"),
        ("mergeStateStatus", "UNSTABLE", "release step"),
        ("mergeStateStatus", "DRAFT", "pair access/setup"),
        ("mergeStateStatus", "HAS_HOOKS", "pair access/setup"),
        ("reviewDecision", "CHANGES_REQUESTED", "pair access/setup"),
    ],
)
def test_unmergeable_pr_fails_immediately(
    scratch, github, monkeypatch, field, state, phase
):
    project, _, _, waits = scratch
    original = check.sync.gh

    def blocked(root, *args, payload=None):
        result = original(root, *args, payload=payload)
        for pr in github["prs"]:
            pr[field] = state
        return result

    monkeypatch.setattr(check.sync, "gh", blocked)
    result = invoke(project)
    assert result.exit_code != 0
    assert phase in result.output
    assert "timed out" not in result.output
    assert not waits
    assert_failed_state(scratch, github)


@pytest.mark.parametrize("phase", ["preparation", "exercise"])
def test_exhausted_budget_reports_its_stage(scratch, monkeypatch, phase):
    project, _, _, _ = scratch
    refs = git(project, "ls-remote", "origin")
    ticks = iter([0, 600] if phase == "preparation" else [0, 0, 599, 600])
    monkeypatch.setattr(check.time, "monotonic", lambda: next(ticks))

    if phase == "preparation":

        def unexpected_exercise(trial):
            pytest.fail("expired exercise started")

        monkeypatch.setattr(check.RoundTrip, "exercise", unexpected_exercise)

    result = invoke(project)
    assert result.exit_code != 0
    assert "Overleaf live check PASS" not in result.output
    if phase == "preparation":
        assert (
            "Overleaf check failed (pair access/setup): "
            "Live check timed out before starting its next phase."
        ) in result.output
        assert_unchanged(scratch, refs)
    else:
        assert (
            "Overleaf check failed (release step): Live check timed out."
            in result.output
        )
        assert not git(project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/*")


@pytest.mark.parametrize("remaining", [0, -0.1])
def test_exhausted_deadline_does_not_enter_its_body(remaining):
    with pytest.raises(check.CheckTimeout, match="timed out"):
        with check.deadline(remaining):
            pytest.fail("expired phase started")


def test_fractional_deadline_is_not_rounded_up():
    with pytest.raises(check.CheckTimeout, match="timed out"):
        with check.deadline(0.01):
            check.signal.pause()


def test_unexpected_error_never_echoes_credential_bearing_commands(
    scratch, monkeypatch
):
    project, _, _, _ = scratch

    refs = git(project, "ls-remote", "origin")

    def fail(trial):
        raise subprocess.CalledProcessError(
            1, ["fixture-command", "credential-sentinel"]
        )

    monkeypatch.setattr(check.RoundTrip, "exercise", fail)
    result = invoke(project)
    assert result.exit_code != 0
    assert "Unexpected CalledProcessError" in result.output
    assert "credential-sentinel" not in result.output
    assert_unchanged(scratch, refs)


def test_recent_check_makes_the_pair_busy_without_changes(scratch):
    project, _, _, _ = scratch
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    git(project, "push", "origin", f"HEAD:{ref}")
    before = git(project, "ls-remote", "origin")
    result = invoke(project)
    assert result.exit_code != 0
    assert "pair busy" in result.output
    assert "release step" not in result.output
    assert git(project, "ls-remote", "origin") == before


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_finishing_check_preserves_a_replacement_owners_lock(scratch, monkeypatch):
    project, _, _, _ = scratch
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    replacement = {}

    def taken_over(trial):
        # A suspended owner resumes after the stale-lock rule let another check
        # claim the pair. Its finally block must not release that new lock.
        old = check.remote_ref(trial.work, ref)
        tree = check.ov.git("mktree", cwd=trial.work, input=b"")
        owner = check.ov.git(
            "commit-tree", tree, cwd=trial.work, input=b"Replacement check\n"
        )
        check.ov.git(
            "push",
            f"--force-with-lease={ref}:{old}",
            "origin",
            f"{owner}:{ref}",
            cwd=trial.work,
        )
        replacement["owner"] = owner
        raise check.ov.SyncError("Original check interrupted")

    monkeypatch.setattr(check.RoundTrip, "exercise", taken_over)
    result = invoke(project)
    assert result.exit_code != 0
    assert "Original check interrupted" in result.output
    assert check.remote_ref(project, ref) == replacement["owner"]
    assert "Could not release the release-check lock" in result.output


@pytest.mark.parametrize(
    "command,option", [("check", "--timeout"), ("sync", "--check-timeout")]
)
def test_timeout_cannot_outlive_check_lock(scratch, command, option):
    project, _, _, _ = scratch
    before = git(project, "ls-remote", "origin")
    result = CliRunner().invoke(
        cli,
        [
            "workspace",
            "overleaf",
            command,
            "--project",
            str(project),
            option,
            str(check.sync.STALE_LOCK_SECONDS),
        ],
    )
    assert result.exit_code != 0
    assert "3540" in result.output
    assert_unchanged(scratch, before)


def test_stalled_lock_acquisition_is_bounded_and_cannot_exercise(scratch, monkeypatch):
    project, _, _, _ = scratch
    before = git(project, "ls-remote", "origin")
    original = check.remote_ref

    def stalled(root, ref):
        if ref.startswith("refs/asta/overleaf-sync-lock/check-"):
            assert check.signal.getitimer(check.signal.ITIMER_REAL)[0] > 0
            check.signal.raise_signal(check.signal.SIGALRM)
            pytest.fail("lock acquisition was not bounded")
        return original(root, ref)

    monkeypatch.setattr(check, "remote_ref", stalled)
    result = invoke(project)
    assert result.exit_code != 0
    assert "pair access/setup" in result.output
    assert "timed out" in result.output
    assert "live check PASS" not in result.output
    assert_unchanged(scratch, before)


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_stale_observer_cannot_delete_a_new_checks_lock(scratch, monkeypatch):
    project, _, _, _ = scratch
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    stale_check_lock(project)
    stale = check.sync.stale_lock
    replacement = {}

    def another_check_claims(root, project_id):
        # Both checks observed the same dead owner. The other one wins before
        # this check deletes it, and now owns the pair with a fresh commit.
        assert stale(root, project_id)
        old = check.remote_ref(root, ref)
        tree = check.ov.git("mktree", cwd=root, input=b"")
        owner = check.ov.git(
            "commit-tree", tree, cwd=root, input=b"Another live check\n"
        )
        check.ov.git(
            "push",
            f"--force-with-lease={ref}:{old}",
            "origin",
            f"{owner}:{ref}",
            cwd=root,
        )
        replacement["owner"] = owner
        replacement["refs"] = git(project, "ls-remote", "origin")
        return True

    monkeypatch.setattr(check.sync, "stale_lock", another_check_claims)
    result = invoke(project)
    assert result.exit_code != 0
    assert "pair busy" in result.output
    assert "release step" not in result.output
    assert check.remote_ref(project, ref) == replacement["owner"]
    assert_unchanged(scratch, replacement["refs"])


def test_failed_stale_lock_deletion_leaves_the_pair_unchanged(scratch, monkeypatch):
    project, _, _, _ = scratch
    ref = "refs/asta/overleaf-sync-lock/check-1234567"
    stale_check_lock(project)
    before = git(project, "ls-remote", "origin")
    original = check.ov.git

    def refused(*args, **kwargs):
        if "push" in args and f":{ref}" in args:
            raise check.ov.SyncError("Cannot delete the stale lock")
        return original(*args, **kwargs)

    monkeypatch.setattr(check.ov, "git", refused)
    result = invoke(project)
    assert result.exit_code != 0
    assert "pair access/setup" in result.output
    assert "Cannot delete the stale lock" in result.output
    assert "pair busy" not in result.output
    assert_unchanged(scratch, before)


def test_stale_check_leftovers_are_cleared_then_checked(scratch, github, monkeypatch):
    project, _, _, _ = scratch
    real_sync = check.RoundTrip.run_sync

    def dies(self):
        real_sync(self)
        raise check.CheckTimeout("killed")

    monkeypatch.setattr(check.RoundTrip, "run_sync", dies)
    assert invoke(project).exit_code != 0
    assert github["prs"]
    # Simulate a check that died while holding its lock an hour ago.
    stale_check_lock(project)
    monkeypatch.setattr(check.RoundTrip, "run_sync", real_sync)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert not github["prs"]
    assert_clean(scratch)
