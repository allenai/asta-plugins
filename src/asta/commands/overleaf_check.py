"""Opt-in live release check on a scratch pair reserved for checks.

Nothing else writes to the pair, so its contents between checks don't matter:
the check only moves it forward and restores nothing. A passing check leaves no
open PR, no lock and no conflict markers on the default branch.
"""

import os
import signal
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import click

from . import overleaf as ov
from . import overleaf_sync as sync

CHECK_DISCOVERY_SECONDS = 30
CHECK_FILE = "asta-release-check.tex"


class CheckTimeout(BaseException):
    """Interrupt nested retry/error handlers, like cancellation."""


class PairSetupError(ov.SyncError):
    """A scratch repository rule or missing check requires setup, not a release fix."""


class PairBusy(ov.SyncError):
    """A recent check holds the pair; nothing was changed."""


@contextmanager
def deadline(seconds):
    """Bound network commands as well as the checks wait."""
    if threading.current_thread() is not threading.main_thread():
        raise ov.SyncError("The live check must run on the main thread.")
    if not hasattr(signal, "SIGALRM"):
        raise ov.SyncError("The live check requires a POSIX runner with SIGALRM.")
    if seconds <= 0:
        raise CheckTimeout("Live check timed out before starting its next phase.")

    def expired(signum, frame):
        raise CheckTimeout("Live check timed out.")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def failure_detail(exc):
    # Arbitrary exception messages can include credential-bearing commands.
    return (
        str(exc)
        if isinstance(exc, (click.ClickException, CheckTimeout, OSError))
        else f"Unexpected {type(exc).__name__}."
    )


def remote_ref(root, ref):
    result = ov.git("ls-remote", "--refs", "origin", ref, cwd=root).split()
    return result[0] if result else ""


def delete_ref(root, ref):
    if tip := remote_ref(root, ref):
        ov.git("push", f"--force-with-lease={ref}:{tip}", "origin", f":{ref}", cwd=root)


class RoundTrip:
    def __init__(self, work, directory, info):
        self.work = work
        self.directory = directory
        self.paper = work / directory
        self.prefix = directory.rstrip("/") + "/"
        self.repo = info["nameWithOwner"]
        self.default = info["defaultBranchRef"]["name"]
        self.config = ov.load_config(self.paper)
        self.project_id = ov.validate_url(self.config["url"]).rsplit("/", 1)[1]
        self.branch = f"asta/overleaf-sync/{self.project_id}"
        self.lock_ref = f"refs/asta/overleaf-sync-lock/check-{self.project_id}"
        self.nonce = uuid4().hex

    def text(self, label):
        return f"% Asta check {self.nonce}: {label}\n".encode()

    @contextmanager
    def lock(self, timeout):
        """Hold the pair; a lock older than the sync's stale rule is a dead check."""
        with deadline(timeout):
            if tip := remote_ref(self.work, self.lock_ref):
                if not sync.stale_lock(self.work, f"check-{self.project_id}"):
                    raise PairBusy("A recent live check holds the scratch pair.")
                try:
                    ov.git(
                        "push",
                        f"--force-with-lease={self.lock_ref}:{tip}",
                        "origin",
                        f":{self.lock_ref}",
                        cwd=self.work,
                    )
                except ov.SyncError as exc:
                    if remote_ref(self.work, self.lock_ref) != tip:
                        raise PairBusy(
                            "Another live check changed the scratch pair lock."
                        ) from exc
                    raise
            owner = ov.git(
                "commit-tree",
                ov.git("mktree", cwd=self.work, input=b""),
                cwd=self.work,
                input=f"Overleaf release check lock {self.nonce}\n".encode(),
            )
            try:
                ov.git(
                    "push",
                    f"--force-with-lease={self.lock_ref}:",
                    "origin",
                    f"{owner}:{self.lock_ref}",
                    cwd=self.work,
                )
            except ov.SyncError as exc:
                raise PairBusy("Another live check claimed the scratch pair.") from exc
        try:
            yield
        finally:
            try:
                with deadline(30):
                    ov.git(
                        "push",
                        f"--force-with-lease={self.lock_ref}:{owner}",
                        "origin",
                        f":{self.lock_ref}",
                        cwd=self.work,
                    )
            except (CheckTimeout, Exception):
                # A leftover lock turns stale, and the next check clears it.
                click.echo("Could not release the release-check lock.", err=True)

    def clear_leftovers(self):
        """Under the check lock, anything a sync left behind is from a dead check."""
        self.close_pr()
        delete_ref(self.work, f"refs/asta/overleaf-sync-lock/{self.project_id}")
        delete_ref(self.work, f"refs/heads/{self.branch}")

    def close_pr(self):
        if pr := self.pr():
            sync.gh(
                self.work,
                "api",
                f"repos/{self.repo}/pulls/{pr['number']}",
                "--method",
                "PATCH",
                payload={"state": "closed"},
            )

    def refresh(self):
        ov.git("fetch", "-q", "origin", self.default, cwd=self.work)
        ov.git("checkout", "--force", "--detach", "FETCH_HEAD", cwd=self.work)

    def commit(self, repo, message, paths):
        ov.git("add", "--", *paths, cwd=repo)
        if ov.git("diff", "--cached", "--name-only", cwd=repo):
            ov.git("commit", "-q", "-m", message, cwd=repo)

    def workspace_edit(self, content):
        self.refresh()
        (self.paper / CHECK_FILE).write_bytes(content)
        self.commit(
            self.work, "Asta live check: workspace edit", [self.prefix + CHECK_FILE]
        )
        ov.git("push", "-q", "origin", f"HEAD:refs/heads/{self.default}", cwd=self.work)

    def coauthor_edit(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "overleaf"
            head = ov.clone(self.config["url"], repo)
            ov.git("reset", "--hard", head, cwd=repo)
            for key in ("user.name", "user.email"):
                value = ov.git("config", "--get", key, cwd=self.work)
                ov.git("config", key, value, cwd=repo)
            (repo / CHECK_FILE).write_bytes(content)
            self.commit(repo, "Asta live check: co-author edit", [CHECK_FILE])
            ov.push(repo, self.work)
        # Read Overleaf's actual commit: its Git integration can translate a push.
        head, _ = self.overleaf_state()
        return head

    def overleaf_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "overleaf"
            head = ov.clone(self.config["url"], repo)
            return head, ov.read_plain_files(repo, head)

    def pr(self):
        return sync.sync_pr(self.work, self.repo, self.branch, self.default)

    def run_sync(self):
        click.get_current_context().invoke(
            ov.sync, project=self.work, directory=self.directory
        )

    def merge_and_wait(self):
        """Poll GitHub while checks run; sync only a completed, mergeable PR."""
        missing_since = None
        while pr := self.pr():
            if pr.get("reviewDecision") in {"REVIEW_REQUIRED", "CHANGES_REQUESTED"}:
                raise PairSetupError(
                    "The scratch PR requires a human review or has requested changes; configure a pair that can merge unattended."
                )
            state = pr.get("mergeStateStatus")
            # UNSTABLE also covers non-required checks still running; the
            # rollup below fails on a completed unsuccessful check instead.
            if pr.get("mergeable") == "CONFLICTING" or state in {"DIRTY", "BEHIND"}:
                raise ov.SyncError(
                    f"The scratch PR cannot merge (mergeStateStatus={state}, mergeable={pr.get('mergeable')}); inspect its conflicts, base branch and checks."
                )
            if state == "DRAFT":
                raise PairSetupError(
                    "The scratch sync PR is a draft; it cannot merge unattended."
                )
            results = pr.get("statusCheckRollup") or []
            if not results:
                # Newly opened PRs can briefly have no rollup while Actions starts.
                if missing_since is None:
                    missing_since = time.monotonic()
                if time.monotonic() - missing_since >= CHECK_DISCOVERY_SECONDS:
                    raise PairSetupError(
                        "No scratch PR checks appeared; configure a successful PR check on the pair."
                    )
                time.sleep(5)
                continue
            missing_since = None
            pending = False
            successful = False
            for result in results:
                if "status" in result:
                    if result["status"] != "COMPLETED":
                        pending = True
                        continue
                    outcome = result.get("conclusion")
                else:
                    outcome = result.get("state")
                    if outcome in {"PENDING", "EXPECTED"}:
                        pending = True
                        continue
                if outcome not in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
                    raise ov.SyncError(
                        "A scratch PR check failed; the live release check cannot pass."
                    )
                successful |= outcome == "SUCCESS"
            if pending:
                time.sleep(5)
                continue
            if not successful:
                raise PairSetupError(
                    "The scratch PR has no successful check; sync requires at least one SUCCESS."
                )
            if state in {"BLOCKED", "HAS_HOOKS"}:
                raise PairSetupError(
                    "Repository rules block the scratch PR; configure a pair that can merge unattended."
                )
            if (
                pr.get("mergeable") == "MERGEABLE"
                and pr.get("mergeStateStatus") == "CLEAN"
            ):
                self.run_sync()
                if not self.pr():
                    break
            time.sleep(5)
        self.refresh()

    def expect(self, actual, expected, step):
        if actual != expected:
            raise ov.SyncError(f"Live check failed during {step}.")

    def expect_pair(self, content, step, base, *, published=False):
        """Both sides hold the same paper, with this step's edit."""
        self.refresh()
        workspace = ov.paper_files(self.work, "HEAD", self.prefix)
        head, files = self.overleaf_state()
        self.expect(workspace.get(CHECK_FILE), content, step + " workspace")
        self.expect(files, workspace, step + " Overleaf")
        config = ov.load_config(self.paper)
        self.expect(
            (config["url"], config["base"]),
            (self.config["url"], base),
            step + " sync metadata",
        )
        if published:
            with ov.published_record(self.work, self.config["url"]) as (
                _,
                recorded,
                source,
            ):
                self.expect(
                    (recorded, source),
                    (head, ov.git("rev-parse", "HEAD", cwd=self.work)),
                    step + " publication record",
                )

    def exercise(self):
        base = self.coauthor_edit(self.text("co-author"))
        self.run_sync()
        if not self.pr():
            raise ov.SyncError("Live check did not open a PR for the co-author edit.")
        self.merge_and_wait()
        self.expect_pair(self.text("co-author"), "co-author merge", base)

        self.workspace_edit(self.text("published workspace"))
        self.run_sync()
        if self.pr():
            raise ov.SyncError("Live check unexpectedly opened a PR while publishing.")
        self.expect_pair(
            self.text("published workspace"),
            "workspace publication",
            base,
            published=True,
        )

        self.workspace_edit(self.text("workspace conflict"))
        base = self.coauthor_edit(self.text("co-author conflict"))
        self.run_sync()
        if not self.pr():
            raise ov.SyncError(
                "Live check failed to retain the conflicting edit in a PR."
            )
        ov.git("fetch", "-q", "origin", self.branch, cwd=self.work)
        ov.git("checkout", "--detach", "FETCH_HEAD", cwd=self.work)
        conflicted = (self.paper / CHECK_FILE).read_bytes()
        if b"<<<<<<<" not in conflicted or b">>>>>>>" not in conflicted:
            raise ov.SyncError(
                "Live check failed to expose the expected conflict markers."
            )
        resolved = self.text("workspace conflict") + self.text("co-author conflict")
        (self.paper / CHECK_FILE).write_bytes(resolved)
        self.commit(
            self.work, "Asta live check: resolve conflict", [self.prefix + CHECK_FILE]
        )
        ov.git("push", "-q", "origin", f"HEAD:refs/heads/{self.branch}", cwd=self.work)
        self.merge_and_wait()
        self.expect_pair(resolved, "resolved publication", base, published=True)
        self.expect(self.pr(), None, "final state (open PR)")
        self.expect(
            remote_ref(self.work, f"refs/asta/overleaf-sync-lock/{self.project_id}"),
            "",
            "final state (sync lock)",
        )


def _check_workspace(project: Path, directory: str, timeout: int):
    timeout = ov.release_check_timeout(None, None, timeout)
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise ov.SyncError(
            "The live check must run on a scratch pair outside CI, where Overleaf credentials already exist."
        )
    started = time.monotonic()
    root, paper, prefix = ov.resolve(project, directory)
    directory = prefix.rstrip("/")
    config = ov.load_config(paper)
    if not config:
        raise PairSetupError(
            "Pair and import the scratch Overleaf project before running check."
        )
    ctx = click.get_current_context()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "workspace"
        with deadline(timeout):
            info = sync.gh(
                root, "repo", "view", "--json", "nameWithOwner,defaultBranchRef"
            )
            ov.git(
                "clone",
                "-q",
                "--",
                ov.git("remote", "get-url", "origin", cwd=root),
                str(work),
                cwd=root,
            )
            ov.foreground_maintenance(work)
            for key in ("user.name", "user.email"):
                value = ov.git("config", "--get", key, cwd=root)
                ov.git("config", key, value, cwd=work)
            if ov.load_config(work / directory) != config:
                raise PairSetupError(
                    "Use the scratch default branch's current Overleaf configuration."
                )
            trial = RoundTrip(work, directory, info)
        with trial.lock(timeout - (time.monotonic() - started)):
            with deadline(timeout - (time.monotonic() - started)):
                trial.clear_leftovers()
                trial.refresh()
                ctx.meta["overleaf_check_phase"] = "release step"
                trial.exercise()
    click.echo(
        "Overleaf live check PASS: co-author merge, publication and conflict resolution."
    )


def check_workspace(project: Path, directory: str, timeout: int):
    """Distinguish a busy pair and pair setup failures from release failures."""
    ctx = click.get_current_context()
    ctx.meta["overleaf_check_phase"] = "pair access/setup"
    try:
        _check_workspace(project, directory, timeout)
    except PairBusy as exc:
        raise PairBusy(f"Overleaf check pair busy: {exc}") from exc
    except (CheckTimeout, Exception) as exc:
        phase = (
            "pair access/setup"
            if isinstance(exc, PairSetupError)
            else ctx.meta["overleaf_check_phase"]
        )
        raise ov.SyncError(
            f"Overleaf check failed ({phase}): {failure_detail(exc)}"
        ) from exc
    finally:
        ctx.meta.pop("overleaf_check_phase", None)
