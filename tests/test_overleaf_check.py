"""The live-check orchestration runs offline over real Git and fake GitHub checks."""

import importlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import click
import pytest
from click.testing import CliRunner

from asta.cli import cli
from tests.test_overleaf_sync import github as github  # noqa: F401
from tests.test_overleaf_sync import prepare
from tests.test_workspace_overleaf import git, overleaf_edit
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
    changed = git(project, "diff", "--name-only", head, "FETCH_HEAD").splitlines()
    assert all(name == "paper/overleaf.json" for name in changed)
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
            pr["statusCheckRollup"] = [{"status": "IN_PROGRESS", "conclusion": None}]
        return result

    monkeypatch.setattr(check.sync, "gh", pending)
    monkeypatch.setattr(
        check.time,
        "sleep",
        lambda seconds: check.signal.raise_signal(check.signal.SIGALRM),
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


@pytest.mark.parametrize("path", ["paper/main.tex", "references.bib"])
def test_check_detects_clobbered_paper_or_workspace_and_restores(
    scratch, monkeypatch, path
):
    project, _, _, _ = scratch
    original = check.RoundTrip.merge_and_wait

    def clobber(trial):
        original(trial)
        (trial.work / path).write_bytes(b"clobbered by a broken release\n")
        trial.commit(trial.work, "Broken release clobbered a paper", [path])
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
    assert "co-author merge" in result.output
    assert "Overleaf live check FAIL" in result.output
    assert_restored(scratch)


def test_refuses_differing_pair_without_changing_it(scratch, github, monkeypatch):
    project, _, _, _ = scratch
    seed = project.parent / "seed"
    from tests.test_workspace_overleaf import overleaf_edit

    overleaf_edit(seed, "main.tex", "an edit already waiting\n")
    # A differing pair is rejected before any write to either remote or GitHub.
    workspace_refs = git(project, "ls-remote", "origin")
    overleaf_refs = git(seed, "ls-remote", "origin")
    pushes = []
    original = check.ov.git

    def observed_git(*args, **kwargs):
        if "push" in args:
            pushes.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(check.ov, "git", observed_git)
    result = invoke(project)
    assert result.exit_code != 0
    assert "identical" in result.output
    assert git(seed, "show", "HEAD:main.tex") == "an edit already waiting"
    assert not github["prs"] and not github["merges"]
    assert not pushes
    assert git(project, "ls-remote", "origin") == workspace_refs
    assert git(seed, "ls-remote", "origin") == overleaf_refs
    assert all(
        args[:2] in {("repo", "view"), ("pr", "list")} for args, _ in github["calls"]
    )


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


@pytest.mark.parametrize("auto_delete", [False, True])
def test_preserves_a_leftover_sync_created_branch(scratch, monkeypatch, auto_delete):
    project, _, head, _ = scratch
    ref = "refs/heads/asta/overleaf-sync/1234567"
    if auto_delete:
        original = check.sync.gh

        def deleting_github(root, *args, payload=None):
            result = original(root, *args, payload=payload)
            if args[:2] == ("pr", "merge"):
                git(project, "push", "origin", f":{ref}")
            return result

        monkeypatch.setattr(check.sync, "gh", deleting_github)
    git(project, "commit", "--allow-empty", "-m", "Sync Overleaf paper")
    old_branch = git(project, "rev-parse", "HEAD")
    git(project, "push", "origin", f"HEAD:{ref}")
    git(project, "reset", "--hard", head)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert git(project, "ls-remote", "origin", ref).split()[0] == old_branch
    git(project, "push", "origin", f":{ref}")
    assert_restored(scratch)


def test_normalizes_a_relative_paper_directory(scratch):
    project, _, _, _ = scratch
    result = invoke(project, "--dir", "./paper")
    assert result.exit_code == 0, result.output
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


@pytest.mark.parametrize("empty_commit", [False, True])
def test_default_commit_during_preflight_is_preserved_without_starting_check(
    scratch, github, monkeypatch, empty_commit
):
    project, baseline, caller_head, _ = scratch
    seed = project.parent / "seed"
    overleaf_refs = git(seed, "ls-remote", "origin")
    original = check.sync.lock
    concurrent_head = []

    @contextmanager
    def lock(root, project_id):
        with original(root, project_id) as acquired:
            if not project_id.startswith("check-"):
                yield acquired
                return
            if not empty_commit:
                (project / "references.bib").write_text("concurrent workspace edit\n")
                git(project, "add", "references.bib")
            git(project, "commit", "--allow-empty", "-m", "Concurrent default commit")
            concurrent_head.append(git(project, "rev-parse", "HEAD"))
            git(project, "push", "origin", "HEAD:main")
            git(project, "reset", "--hard", caller_head)
            yield acquired

    monkeypatch.setattr(check.sync, "lock", lock)
    result = invoke(project)
    assert result.exit_code != 0
    assert "pair access/setup" in result.output
    assert "default branch changed during preflight" in result.output
    assert "live check PASS" not in result.output
    assert (
        git(project, "ls-remote", "origin", "refs/heads/main").split()[0]
        == concurrent_head[0]
    )
    git(project, "fetch", "origin", "main")
    assert check.ov.paper_files(project, "FETCH_HEAD", "paper/") == baseline
    if not empty_commit:
        assert (
            git(project, "show", "FETCH_HEAD:references.bib")
            == "concurrent workspace edit"
        )
    assert git(project, "rev-parse", "HEAD") == caller_head
    assert git(project, "status", "--porcelain") == ""
    assert git(seed, "ls-remote", "origin") == overleaf_refs
    assert not github["prs"] and not github["merges"]
    assert not git(project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/*")
    assert not git(project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/*")


def test_pr_close_timeout_still_restores_both_contents(scratch, github, monkeypatch):
    project, _, _, _ = scratch
    original_sync = check.RoundTrip.run_sync
    original_deadline = check.deadline
    restoration_limits = []

    def fail_sync(trial):
        original_sync(trial)
        raise check.ov.SyncError("Original exercise failure")

    @contextmanager
    def fast_restoration(seconds):
        # Exercise a real timer expiry in PR closure without waiting 30 seconds.
        if seconds in {30, 60, 15}:
            restoration_limits.append(seconds)
        with original_deadline(1 if seconds == 30 else seconds):
            yield

    def blocked_close(trial):
        check.signal.pause()

    monkeypatch.setattr(check.RoundTrip, "run_sync", fail_sync)
    monkeypatch.setattr(check.RoundTrip, "close_pr", blocked_close)
    monkeypatch.setattr(check, "deadline", fast_restoration)
    result = invoke(project)
    assert result.exit_code != 0
    assert "closing the check PR (timed out)" in result.output
    assert "Original exercise failure" in result.output
    assert "Scratch restoration failed" in result.output
    assert "live check PASS" not in result.output
    assert restoration_limits[:5] == [30, 60, 60, 15, 15]
    # The unclosed PR remains visible for recovery; both contents and refs recover.
    assert github["prs"]
    assert_restored(scratch)


@pytest.mark.parametrize("blocked", ["restore_overleaf", "restore_workspace"])
def test_content_restoration_timeout_does_not_skip_later_actions(
    scratch, monkeypatch, blocked
):
    project, _, _, _ = scratch
    attempts = []
    for name in (
        "restore_overleaf",
        "restore_workspace",
        "restore_branch",
        "verify_restoration",
    ):
        original = getattr(check.RoundTrip, name)

        def restore(trial, *args, operation=name, action=original):
            attempts.append(operation)
            result = action(trial, *args)
            if operation == blocked:
                check.signal.raise_signal(check.signal.SIGALRM)
            return result

        monkeypatch.setattr(check.RoundTrip, name, restore)
    result = invoke(project)
    assert result.exit_code != 0
    assert "timed out" in result.output
    assert "Scratch restoration failed" in result.output
    assert "live check PASS" not in result.output
    assert attempts == [
        "restore_overleaf",
        "restore_workspace",
        "restore_branch",
        "verify_restoration",
    ]
    assert_restored(scratch)


@pytest.mark.parametrize(
    ("stage", "content"),
    [
        ("workspace publication", b"% Asta check: published workspace\n"),
        (
            "resolved publication",
            b"% Asta check: workspace conflict\n% Asta check: co-author conflict\n",
        ),
    ],
)
@pytest.mark.parametrize(
    "metadata", ["base", "overleaf", "workspace", "missing", "exported config"]
)
def test_stale_metadata_fails_before_restoration_can_hide_it(
    scratch, monkeypatch, stage, content, metadata
):
    project, _, _, _ = scratch
    original = check.RoundTrip.run_sync
    injected = []

    def broken_sync(trial):
        original(trial)
        git(trial.work, "fetch", "origin", trial.default)
        if (
            check.ov.paper_files(trial.work, "FETCH_HEAD", trial.prefix).get(trial.name)
            != content
            or trial.pr()
        ):
            return
        injected.append(metadata)
        trial.refresh()
        if metadata == "base":
            check.ov.save_config(trial.paper, trial.config["url"], trial.config["base"])
            trial.commit(
                trial.work,
                "Broken release retained stale base",
                [trial.prefix + check.ov.CONFIG],
            )
            git(trial.work, "push", "origin", f"HEAD:refs/heads/{trial.default}")
        elif metadata == "missing":
            git(
                trial.work,
                "push",
                "origin",
                f":{check.ov.record_ref(trial.config['url'])}",
            )
        elif metadata == "exported config":
            seed = project.parent / "seed"
            git(seed, "pull", "--ff-only", "origin", "master")
            overleaf_edit(seed, check.ov.CONFIG, "metadata leaked into Overleaf\n")
        else:
            with check.ov.published_record(trial.work, trial.config["url"]) as (
                previous,
                overleaf,
                workspace,
            ):
                check.ov.record_publication(
                    trial.work,
                    trial.config["url"],
                    previous,
                    trial.config["base"] if metadata == "overleaf" else overleaf,
                    trial.workspace_base if metadata == "workspace" else workspace,
                    [],
                )

    monkeypatch.setattr(check.RoundTrip, "run_sync", broken_sync)
    result = invoke(project)
    assert injected == [metadata]
    assert result.exit_code != 0
    expected = {
        "base": "sync metadata",
        "exported config": "Overleaf",
    }.get(metadata, "publication record")
    assert f"{stage} {expected}" in result.output
    assert "release step" in result.output
    assert "live check PASS" not in result.output
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
    assert "Injected check failure" in result.output
    assert "live check PASS" not in result.output
    assert_restored(scratch)


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
    assert "Another live check" in result.output
    assert git(project, "ls-remote", "origin", held)
    git(project, "push", "origin", f":{held}")
    assert not git(project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/*")


@pytest.mark.parametrize(
    "failure",
    [
        KeyError("number"),
        subprocess.CalledProcessError(1, ["fixture"]),
        RuntimeError("unexpected"),
    ],
)
def test_unexpected_cleanup_error_does_not_skip_restoring_remotes(
    scratch, github, monkeypatch, failure
):
    project, _, _, _ = scratch
    original = check.RoundTrip.run_sync

    def fail_sync(trial):
        original(trial)
        raise check.ov.SyncError("Original exercise failure")

    def fail_close(trial):
        raise failure

    monkeypatch.setattr(check.RoundTrip, "run_sync", fail_sync)
    monkeypatch.setattr(check.RoundTrip, "close_pr", fail_close)
    result = invoke(project)
    assert result.exit_code != 0
    assert "Original exercise failure" in result.output
    assert "Scratch restoration failed" in result.output
    assert "live check PASS" not in result.output
    assert_restored(scratch)


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
    assert not waits and not github["merges"]
    assert_restored(scratch)


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
    assert not github["merges"]
    assert_restored(scratch)
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
    assert_restored(scratch)


def test_main_thread_requirement_is_a_clear_error():
    def run():
        with check.deadline(1):
            pytest.fail("worker thread must be refused before starting")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(check.ov.SyncError, match="main thread"):
            pool.submit(run).result()


def test_check_lock_acquisition_is_bounded(scratch, monkeypatch):
    project, _, _, _ = scratch

    @contextmanager
    def blocked(root, project_id):
        check.signal.pause()
        yield True

    monkeypatch.setattr(check.sync, "lock", blocked)
    result = invoke(project, "--timeout", "1")
    assert result.exit_code != 0
    assert "pair access/setup" in result.output and "timed out" in result.output
    assert_restored(scratch)


def test_check_lock_release_has_a_deadline(scratch, monkeypatch):
    project, _, _, _ = scratch
    original = check.sync.lock

    @contextmanager
    def lock(root, project_id):
        with original(root, project_id) as acquired:
            yield acquired
            if project_id.startswith("check-"):
                # Exercise the real installed signal handler during lock release.
                check.signal.raise_signal(check.signal.SIGALRM)

    monkeypatch.setattr(check.sync, "lock", lock)
    result = invoke(project)
    assert result.exit_code != 0
    assert "timed out" in result.output
    assert "live check PASS" not in result.output
    assert_restored(scratch)
