"""Opt-in live release check on an exclusively reserved, disposable scratch pair."""

import os
import signal
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import click

from . import overleaf as ov
from . import overleaf_sync as sync


class CheckTimeout(ov.SyncError):
    """Do not swallow a restoration deadline while attempting other cleanup."""


@contextmanager
def deadline(seconds):
    """Bound network commands as well as the checks wait, including on failure."""
    if not hasattr(signal, "SIGALRM"):
        raise ov.SyncError("The live check requires a POSIX runner with SIGALRM.")

    def expired(signum, frame):
        raise CheckTimeout(
            "Live check timed out; inspect the scratch pair before retrying."
        )

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def remote_ref(root, ref):
    result = ov.git("ls-remote", "--refs", "origin", ref, cwd=root).split()
    return result[0] if result else ""


class RoundTrip:
    def __init__(self, work, directory, info, baseline):
        self.work = work
        self.directory = directory
        self.paper = work / directory
        self.prefix = directory.rstrip("/") + "/"
        self.repo = info["nameWithOwner"]
        self.default = info["defaultBranchRef"]["name"]
        self.config = ov.load_config(self.paper)
        self.project_id = self.config["url"].rsplit("/", 1)[1]
        self.branch = f"asta/overleaf-sync/{self.project_id}"
        self.initial_branch = remote_ref(work, f"refs/heads/{self.branch}")
        self.workspace_base = ov.git("rev-parse", "HEAD", cwd=work)
        self.outside_paper = {
            name: value
            for name, value in ov.tree(work, "HEAD").items()
            if not name.startswith(self.prefix)
        }
        self.baseline = baseline
        self.name = f"asta-release-check-{uuid4().hex}.tex"
        self.started = False

    def refresh(self):
        ov.git("fetch", "-q", "origin", self.default, cwd=self.work)
        ov.git("checkout", "--detach", "FETCH_HEAD", cwd=self.work)

    def commit(self, repo, message, paths):
        ov.git("add", "--", *paths, cwd=repo)
        if ov.git("diff", "--cached", "--name-only", cwd=repo):
            ov.git("commit", "-q", "-m", message, cwd=repo)

    def workspace_edit(self, content):
        self.refresh()
        (self.paper / self.name).write_bytes(content)
        self.commit(
            self.work, "Asta live check: workspace edit", [self.prefix + self.name]
        )
        ov.git("push", "-q", "origin", f"HEAD:refs/heads/{self.default}", cwd=self.work)

    def coauthor_edit(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "overleaf"
            head = ov.clone(self.config["url"], repo)
            ov.git("reset", "--hard", head, cwd=repo)
            self.identity(repo)
            (repo / self.name).write_bytes(content)
            self.commit(repo, "Asta live check: co-author edit", [self.name])
            ov.push(repo, self.work)

    def identity(self, repo):
        for key in ("user.name", "user.email"):
            ov.git(
                "config", key, ov.git("config", "--get", key, cwd=self.work), cwd=repo
            )

    def read_overleaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "overleaf"
            head = ov.clone(self.config["url"], repo)
            return ov.paper_files(repo, head)

    def pr(self):
        return sync.sync_pr(self.work, self.repo, self.branch, self.default)

    def run_sync(self):
        click.get_current_context().invoke(
            ov.sync, project=self.work, directory=self.directory
        )
        self.pr()

    def merge_and_wait(self):
        """A scheduler normally returns here; this check owns the quiet reruns."""
        while pr := self.pr():
            for result in pr.get("statusCheckRollup") or []:
                outcome = result.get("conclusion", result.get("state"))
                if outcome in {
                    "FAILURE",
                    "ERROR",
                    "CANCELLED",
                    "TIMED_OUT",
                    "ACTION_REQUIRED",
                }:
                    raise ov.SyncError(
                        "A scratch PR check failed; the live release check cannot pass."
                    )
            self.run_sync()
            if self.pr():
                time.sleep(5)
        self.refresh()

    def expect(self, actual, expected, step):
        if actual != expected:
            raise ov.SyncError(
                f"Live check failed during {step}; scratch restoration follows."
            )

    def expect_pair(self, content, step):
        expected = self.baseline | {self.name: content}
        self.refresh()
        outside = {
            name: value
            for name, value in ov.tree(self.work, "HEAD").items()
            if not name.startswith(self.prefix)
        }
        self.expect(outside, self.outside_paper, step + " outside the paper")
        self.expect(
            ov.paper_files(self.work, "HEAD", self.prefix),
            expected,
            step + " workspace",
        )
        self.expect(self.read_overleaf(), expected, step + " Overleaf")

    def exercise(self):
        self.started = True  # A failed push may have reached its remote.
        self.coauthor_edit(b"% Asta check: co-author\n")
        self.run_sync()
        if not self.pr():
            raise ov.SyncError("Live check did not open a PR for the co-author edit.")
        self.merge_and_wait()
        self.expect_pair(b"% Asta check: co-author\n", "co-author merge")

        self.workspace_edit(b"% Asta check: published workspace\n")
        self.run_sync()
        if self.pr():
            raise ov.SyncError("Live check unexpectedly opened a PR while publishing.")
        self.expect_pair(
            b"% Asta check: published workspace\n", "workspace publication"
        )

        self.workspace_edit(b"% Asta check: workspace conflict\n")
        self.coauthor_edit(b"% Asta check: co-author conflict\n")
        self.run_sync()
        pr = self.pr()
        if not pr:
            raise ov.SyncError(
                "Live check failed to retain the conflicting edit in a PR."
            )
        ov.git("fetch", "-q", "origin", self.branch, cwd=self.work)
        ov.git("checkout", "--detach", "FETCH_HEAD", cwd=self.work)
        conflicted = (self.paper / self.name).read_bytes()
        if b"<<<<<<<" not in conflicted or b">>>>>>>" not in conflicted:
            raise ov.SyncError(
                "Live check failed to expose the expected conflict markers."
            )
        resolved = (
            b"% Asta check: workspace conflict\n% Asta check: co-author conflict\n"
        )
        (self.paper / self.name).write_bytes(resolved)
        self.commit(
            self.work, "Asta live check: resolve conflict", [self.prefix + self.name]
        )
        ov.git("push", "-q", "origin", f"HEAD:refs/heads/{self.branch}", cwd=self.work)
        self.merge_and_wait()
        self.expect_pair(resolved, "resolved publication")

    def close_pr(self):
        pr = self.pr()
        if pr:
            sync.gh(
                self.work,
                "api",
                f"repos/{self.repo}/pulls/{pr['number']}",
                "--method",
                "PATCH",
                payload={"state": "closed"},
            )

    def restore_overleaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "overleaf"
            head = ov.clone(self.config["url"], repo)
            ov.git("reset", "--hard", head, cwd=repo)
            self.identity(repo)
            tracked = ov.read_plain_files(repo, "HEAD")
            for name in tracked.keys() - self.baseline.keys():
                ov.git("rm", "--", name, cwd=repo)
            ov.write_files(self.baseline, repo)
            self.commit(
                repo,
                "Asta live check: restore scratch paper",
                sorted(self.baseline),
            )
            if ov.git("rev-parse", "HEAD", cwd=repo) != head:
                ov.push(repo, self.work)
                head = ov.confirm_publication(
                    repo, ov.git("rev-parse", "HEAD", cwd=repo), head
                )
        return head

    def restore_workspace(self, head):
        # Only this command's disposable clone is reset; a failed commit may
        # have left edits that must not prevent restoration of the remote.
        ov.git("fetch", "-q", "origin", self.default, cwd=self.work)
        ov.git("checkout", "--force", "--detach", "FETCH_HEAD", cwd=self.work)
        # Restore the original tracked tree, including non-paper files a broken
        # release changed. HEAD stays current, keeping the cleanup fast-forward.
        ov.git("read-tree", "--reset", "-u", self.workspace_base, cwd=self.work)
        ov.save_config(self.paper, self.config["url"], head or self.config["base"])
        self.commit(
            self.work,
            "Asta live check: restore scratch workspace",
            [self.prefix + ov.CONFIG],
        )
        ov.git("push", "-q", "origin", f"HEAD:refs/heads/{self.default}", cwd=self.work)
        if head:
            self.restore_record(head)

    def restore_record(self, head):
        with ov.published_record(self.work, self.config["url"], publishing=True) as (
            previous,
            _,
            _,
        ):
            identity = []
            for key in ("user.name", "user.email"):
                identity += [
                    "-c",
                    f"{key}={ov.git('config', '--get', key, cwd=self.work)}",
                ]
            ov.record_publication(
                self.work,
                self.config["url"],
                previous,
                head,
                ov.git("rev-parse", "HEAD", cwd=self.work),
                identity,
            )

    def restore_branch(self):
        branch_tip = remote_ref(self.work, f"refs/heads/{self.branch}")
        if branch_tip:
            ov.git(
                "push",
                f"--force-with-lease=refs/heads/{self.branch}:{branch_tip}",
                "origin",
                f"{self.initial_branch}:refs/heads/{self.branch}",
                cwd=self.work,
            )

    def verify_restoration(self):
        self.expect(self.read_overleaf(), self.baseline, "Overleaf restoration")
        self.refresh()
        self.expect(
            ov.paper_files(self.work, "HEAD", self.prefix),
            self.baseline,
            "workspace restoration",
        )
        outside = {
            name: value
            for name, value in ov.tree(self.work, "HEAD").items()
            if not name.startswith(self.prefix)
        }
        self.expect(
            outside, self.outside_paper, "workspace restoration outside the paper"
        )

    def restore(self):
        """Try both remotes even when one independent cleanup operation fails."""
        if not self.started:
            return
        failures = []

        def attempt(label, action):
            try:
                return action()
            except CheckTimeout:
                raise
            except (click.ClickException, OSError):
                failures.append(label)
                click.echo(f"Scratch restoration could not complete {label}.", err=True)

        attempt("closing the check PR", self.close_pr)
        head = attempt("Overleaf contents", self.restore_overleaf)
        attempt(
            "workspace contents and sync record", lambda: self.restore_workspace(head)
        )
        attempt("restoring the reserved branch", self.restore_branch)
        attempt("content verification", self.verify_restoration)
        if failures:
            raise ov.SyncError(
                "Scratch restoration failed; inspect both sides and the check PR before retrying."
            )


def check_workspace(project: Path, directory: str, timeout: int):
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise ov.SyncError(
            "The live check must run on a scratch pair outside CI, where Overleaf credentials already exist."
        )
    started = time.monotonic()
    root, paper, prefix = ov.resolve(project, directory)
    directory = prefix.rstrip("/")
    ov.require_clean(root, paper)
    config = ov.load_config(paper)
    if not config:
        raise ov.SyncError(
            "Pair and import the scratch Overleaf project before running check."
        )
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
            for key in ("user.name", "user.email"):
                ov.git(
                    "config", key, ov.git("config", "--get", key, cwd=root), cwd=work
                )
            cloned_config = ov.load_config(work / directory)
            if cloned_config != config:
                raise ov.SyncError(
                    "Use the scratch default branch's current Overleaf configuration."
                )
            overleaf = Path(tmp) / "overleaf"
            head = ov.clone(config["url"], overleaf)
            baseline = ov.read_plain_files(overleaf, head)
            if ov.CONFIG in baseline:
                raise ov.SyncError(
                    "The scratch Overleaf project contains the reserved overleaf.json filename; move it aside before check."
                )
            if not baseline or baseline != ov.paper_files(work, "HEAD", prefix):
                raise ov.SyncError(
                    "The scratch pair must already have identical, nonempty paper contents."
                )
            trial = RoundTrip(work, directory, info, baseline)
            if trial.pr():
                raise ov.SyncError("Close the scratch sync PR before check.")
            if trial.initial_branch and not sync.owned_branch(
                work,
                ov.git("rev-parse", "HEAD", cwd=work),
                trial.initial_branch,
                prefix,
            ):
                raise ov.SyncError(
                    "The reserved sync branch has unrelated work; move it aside before check."
                )
            if remote_ref(work, f"refs/asta/overleaf-sync-lock/{trial.project_id}"):
                raise ov.SyncError(
                    "A scratch sync run owns the lock; finish or recover it before check."
                )
        # One check owns the scratch pair across all of its synchronous sync calls.
        with sync.lock(work, f"check-{trial.project_id}") as acquired:
            if not acquired:
                raise ov.SyncError(
                    "Another live check owns the scratch pair; wait for it to finish."
                )
            ctx = click.get_current_context()
            ctx.meta["overleaf_check"] = True
            try:
                try:
                    with deadline(max(1, int(timeout - (time.monotonic() - started)))):
                        # A normal sync may have started while preflight was
                        # reading the pair. Recheck after claiming the outer lock.
                        if remote_ref(
                            work, f"refs/asta/overleaf-sync-lock/{trial.project_id}"
                        ):
                            raise ov.SyncError(
                                "A scratch sync run acquired its lock during preflight; retry when it finishes."
                            )
                        trial.refresh()
                        if (
                            trial.pr()
                            or remote_ref(work, f"refs/heads/{trial.branch}")
                            != trial.initial_branch
                        ):
                            raise ov.SyncError(
                                "The scratch sync branch changed during preflight; inspect it before retrying."
                            )
                        if (
                            trial.read_overleaf() != baseline
                            or ov.paper_files(work, "HEAD", prefix) != baseline
                        ):
                            raise ov.SyncError(
                                "The scratch pair changed during preflight; inspect it before retrying."
                            )
                        trial.exercise()
                finally:
                    with deadline(180):
                        trial.restore()
            finally:
                ctx.meta.pop("overleaf_check", None)
    click.echo(
        "Overleaf live check PASS: co-author merge, publication, conflict resolution and restoration."
    )
