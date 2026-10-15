"""Runner-independent, serialized Overleaf synchronization through a GitHub PR."""

import json
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import click

from . import overleaf as ov

LABEL = "asta:overleaf-sync"
MARKER = "<!-- asta-overleaf-sync -->"
DEFAULT_BODY = (
    MARKER + "\n\nImport co-author edits before publishing the default branch."
)
BUILD_CONFIGS = {"latexmkrc", ".latexmkrc"}
CONFLICT_LABEL = re.compile(rb"(?m)^(?:<<<<<<<|>>>>>>>|\|{7})(?:[ \t]|\r?$)")
FIELDS = "isCrossRepository,headRepositoryOwner,number,url,headRefOid,baseRefName,body,labels,mergeable,mergeStateStatus,statusCheckRollup"
STALE_LOCK_SECONDS = 3600  # Reporting threshold only; never expires ownership.
SYNC_SUBJECTS = {
    "Sync Overleaf paper",
    "Merge current workspace paper into Overleaf sync",
}


def gh(root: Path, *args: str, payload=None):
    """Never include transport diagnostics (which may contain credentials)."""
    env = ov.git_environment()
    env.update(GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            command = ["gh", *args]
            if payload is not None:
                body = Path(tmp) / "body.json"
                body.write_text(json.dumps(payload))
                if "--method" not in args:
                    command += ["--method", "POST"]
                command += ["--input", str(body)]
            result = subprocess.run(
                command, cwd=root, env=env, capture_output=True, timeout=90
            )
    except (OSError, subprocess.TimeoutExpired):
        raise ov.SyncError(
            "GitHub command unavailable or timed out; check gh authentication and retry."
        ) from None
    if result.returncode:
        raise ov.SyncError(
            "GitHub request refused; check repository permissions, rules and gh authentication, then retry."
        )
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return result.stdout.decode(errors="replace")


@contextmanager
def lock(root: Path, project_id: str):
    """A remote compare-and-swap serializes different machines, not just processes.

    No expiring lease: a paused process cannot resume after a successor acquired
    its lock. A killed owner requires the documented explicit recovery.
    """
    ref = f"refs/asta/overleaf-sync-lock/{project_id}"
    if ov.git("ls-remote", "--refs", "origin", ref, cwd=root):
        yield False
        return
    empty = ov.git("mktree", cwd=root, input=b"")
    owner = ov.git(
        "commit-tree",
        empty,
        cwd=root,
        input=f"Overleaf sync lock {uuid4().hex}\n".encode(),
    )
    try:
        ov.git(
            "push", f"--force-with-lease={ref}:", "origin", f"{owner}:{ref}", cwd=root
        )
    except ov.SyncError:
        if ov.git("ls-remote", "--refs", "origin", ref, cwd=root):
            yield False
            return
        raise
    failed = False
    try:
        yield True
    except BaseException:
        failed = True
        raise
    finally:
        try:
            ov.git(
                "push",
                f"--force-with-lease={ref}:{owner}",
                "origin",
                f":{ref}",
                cwd=root,
            )
        except ov.SyncError:
            if not failed:
                raise
            click.echo(
                "Could not release the sync lock; use interrupted-run recovery.",
                err=True,
            )


def stale_lock(root: Path, project_id: str) -> bool:
    ref = f"refs/asta/overleaf-sync-lock/{project_id}"
    ov.git("fetch", "--no-tags", "origin", ref, cwd=root)
    created = int(ov.git("show", "-s", "--format=%ct", "FETCH_HEAD", cwd=root))
    return time.time() - created >= STALE_LOCK_SECONDS


def waiting_message(pr: dict, head: str) -> str:
    state = pr.get("mergeStateStatus", "UNKNOWN")
    mergeable = pr.get("mergeable", "UNKNOWN")
    action = {
        "BLOCKED": "A person must supply required approvals or satisfy repository rules; inspect required reviews and checks.",
        "UNSTABLE": "A person must fix failing checks, then rerun sync.",
        "UNKNOWN": "GitHub is still computing merge eligibility; retry sync after it settles.",
        "BEHIND": "Update the sync branch with the default branch and rerun its checks.",
        "DIRTY": "A person must resolve merge conflicts on the sync PR.",
        "DRAFT": "A person must mark the sync PR ready when its review is complete.",
    }.get(state, "Wait for completed successful checks; fix any failing checks.")
    if pr.get("headRefOid") != head:
        action = (
            "The sync head changed; rerun sync and wait for checks on the new head."
        )
    elif mergeable == "CONFLICTING":
        action = "A person must resolve merge conflicts on the sync PR."
    return f"Sync PR mergeStateStatus={state}, mergeable={mergeable}. {action}"


def checks_pass(pr: dict) -> bool:
    checks = pr.get("statusCheckRollup") or []
    if not checks:
        return False
    outcomes = []
    for check in checks:
        if "conclusion" in check:
            if check.get("status") != "COMPLETED":
                return False
            outcomes.append(check.get("conclusion"))
        else:
            outcomes.append(check.get("state"))
    return "SUCCESS" in outcomes and all(
        x in {"SUCCESS", "NEUTRAL", "SKIPPED"} for x in outcomes
    )


def report(root: Path, repo: str, project_id: str, message: str, pr=None):
    """One persistent repo-visible status, edited only when its contents change."""
    body = f"{MARKER}\n\n{message}\n\nRecovery: {ov.RECOVERY}"
    if pr:
        if pr["body"] != body:
            gh(
                root,
                "api",
                f"repos/{repo}/pulls/{pr['number']}",
                "--method",
                "PATCH",
                payload={"body": body},
            )
        return
    title = f"Overleaf sync needs attention ({project_id})"
    issues = gh(
        root, "api", f"repos/{repo}/issues?state=open&labels={LABEL}&per_page=100"
    )
    matches = [
        x for x in issues if x["title"] == title and MARKER in (x.get("body") or "")
    ]
    if matches:
        if matches[0]["body"] != body:
            gh(
                root,
                "api",
                f"repos/{repo}/issues/{matches[0]['number']}",
                "--method",
                "PATCH",
                payload={"body": body},
            )
    else:
        gh(
            root,
            "api",
            f"repos/{repo}/issues",
            payload={"title": title, "body": body, "labels": [LABEL]},
        )


def pull_into(root: Path, directory: str) -> bool:
    try:
        click.get_current_context().invoke(
            ov.pull, url=None, directory=directory, project=root
        )
    except SystemExit as exc:
        if exc.code != ov.CONFLICT_EXIT:
            raise
        return True
    return False


def changed_paths(work: Path, *args: str) -> list[str]:
    # NUL-delimited so Git never quotes paths with newlines or unusual bytes.
    output = os.fsdecode(ov.git_bytes("diff", "-z", "--name-only", *args, cwd=work))
    return [name for name in output.split("\0") if name]


class BuildConfigError(ov.SyncError):
    """Always reported on the labeled issue, even when a sync PR is open."""


def refuse_build_configs(paths: list[str]) -> None:
    configs = [name for name in paths if Path(name).name.lower() in BUILD_CONFIGS]
    if configs:
        raise BuildConfigError(
            "Executable LaTeX build configuration changed: "
            + ", ".join(map(repr, configs))
            + "; a person must review and import these changes manually; nothing pushed."
        )


def conflict_files(root: Path, prefix: str):
    return sorted(
        name
        for name, data in ov.paper_files(root, "HEAD", prefix).items()
        if Path(name).suffix.lower() in ov.MERGE_SUFFIXES
        and b"\0" not in data
        and (
            CONFLICT_LABEL.search(data)
            or (
                Path(name).suffix.lower() not in {".md", ".txt"}
                and re.search(rb"(?m)^=======\r?$", data)
            )
        )
    )


def reset_status(root: Path, repo: str, pr: dict):
    if pr["body"] != DEFAULT_BODY:
        gh(
            root,
            "api",
            f"repos/{repo}/pulls/{pr['number']}",
            "--method",
            "PATCH",
            payload={"body": DEFAULT_BODY},
        )
        pr["body"] = DEFAULT_BODY


def conflict_message(
    root: Path, tip: str, paths: list[str], pr_url: str = "the sync PR"
):
    # Name the latest workspace change to each conflicted file, not an unrelated
    # default tip or the latest edit anywhere in the paper.
    commits = sorted(
        {
            ov.git("log", "-1", "--format=%H", tip, "--", path, cwd=root)
            for path in paths
        }
        - {""}
    )
    return (
        "Overleaf sync conflicts in "
        + ", ".join(paths)
        + "; workspace changes to these files: "
        + ", ".join(commits)
        + f"; each change's author must resolve the conflict in {pr_url}."
    )


def credits(root: Path, config: dict, new_base: str) -> list[str]:
    if new_base == config["base"]:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        remote = Path(tmp) / "overleaf"
        ov.clone(config["url"], remote)
        # Read actual Git authors, never infer identities from names or handles.
        authors = ov.git(
            "log", "--format=%aN <%aE>", f"{config['base']}..{new_base}", cwd=remote
        )
    return sorted(
        {
            x
            for x in authors.split("\n")
            if re.fullmatch(r"[^<>\r\n\0]+ <[^<>\r\n\0]+>", x)
        }
    )


def only_recorded_base_changed(root, prefix, before, after):
    names = ov.git("diff", "--name-only", "HEAD", "--", prefix, cwd=root).splitlines()
    if names != [prefix + ov.CONFIG] or before.get("url") != after.get("url"):
        return False
    with ov.published_record(root, before["url"]) as (record, recorded, source):
        if recorded != after["base"]:
            return False
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "overleaf"
            ov.clone(before["url"], repo)
            with ov.default_branch(root) as (default, _):
                trusted = ov.reviewed_record(
                    root,
                    repo,
                    prefix,
                    default,
                    recorded,
                    source,
                    record=record,
                    base=before["base"],
                )
        return trusted == after["base"]


def sync_pr(root: Path, repo: str, branch: str, default_name: str):
    """The open sync PR on the reserved branch, refusing duplicates or strangers."""
    prs = gh(
        root,
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--head",
        branch,
        "--json",
        FIELDS,
    )
    # A fork can reuse the branch name and body marker. Never mutate its PR.
    owner = repo.split("/", 1)[0].lower()
    prs = [
        pr
        for pr in prs
        if pr.get("isCrossRepository") is False
        and (pr.get("headRepositoryOwner") or {}).get("login", "").lower() == owner
    ]
    if len(prs) > 1:
        raise ov.SyncError(
            "Multiple sync PRs exist; close the duplicate before retrying."
        )
    pr = prs[0] if prs else None
    if pr and (
        MARKER not in (pr.get("body") or "") or pr["baseRefName"] != default_name
    ):
        raise ov.SyncError(
            "The reserved sync branch has an unrelated PR; move it aside before retrying."
        )
    return pr


def owned_branch(work: Path, tip: str, old_head: str, prefix: str) -> bool:
    """Whether a PR-less reserved branch holds only sync-created paper commits."""
    try:
        ov.git("cat-file", "-e", f"{old_head}^{{commit}}", cwd=work)
    except ov.GitCommandError:
        raise ov.SyncError("Sync branch changed while reading it; retry.")
    subjects = ov.git("log", "--format=%s", f"{tip}..{old_head}", cwd=work).splitlines()
    if any(x not in SYNC_SUBJECTS for x in subjects):
        return False
    ancestor = ov.git("merge-base", tip, old_head, cwd=work)
    changed = ov.git("diff", "--name-only", ancestor, old_head, cwd=work)
    return all(name.startswith(prefix) for name in changed.splitlines())


def sync_workspace(project: Path, directory: str):
    root, paper, prefix = ov.resolve(project, directory)
    # resolve() currently guarantees this; keep the write boundary explicit here.
    if not prefix or not prefix.endswith("/"):
        raise ov.SyncError("Sync requires a non-empty paper subdirectory.")
    config = ov.load_config(paper)
    if not config:
        raise ov.SyncError(
            "Import and commit the paper with overleaf pull before scheduling sync."
        )
    project_id = ov.validate_url(config["url"]).rsplit("/", 1)[1]
    info = gh(root, "repo", "view", "--json", "nameWithOwner,defaultBranchRef")
    repo = info["nameWithOwner"]
    default_name = info["defaultBranchRef"]["name"]
    branch = f"asta/overleaf-sync/{project_id}"
    # Label creation is idempotent; no repository settings or protections change.
    gh(
        root,
        "label",
        "create",
        LABEL,
        "--repo",
        repo,
        "--color",
        "5B7C99",
        "--description",
        "Overleaf paper synchronization",
        "--force",
    )
    identity = {}
    for key in ("user.name", "user.email"):
        try:
            value = ov.git("config", "--get", key, cwd=root)
        except ov.GitCommandError as exc:
            if exc.returncode != 1:
                raise
            value = ""
        if not value.strip():
            message = f"Configure Git {key} before scheduling sync."
            try:
                report(root, repo, project_id, message)
            except ov.SyncError:
                click.echo(
                    "Could not report the missing Git identity on GitHub.", err=True
                )
            raise ov.SyncError(message)
        identity[key] = value
    with lock(root, project_id) as acquired:
        if not acquired:
            if not stale_lock(root, project_id):
                click.echo(
                    "Overleaf sync lock is held by a recent run; leaving its status unchanged."
                )
                return
            message = "Overleaf sync lock is held; confirm the owning run is active, or recover its interrupted lock."
            try:
                try:
                    pr = sync_pr(root, repo, branch, default_name)
                except ov.SyncError:
                    pr = None
                report(root, repo, project_id, message, pr)
            except ov.SyncError:
                click.echo("Could not report the held lock on GitHub.", err=True)
            raise ov.SyncError(message)
        pr = None
        try:
            pr = sync_pr(root, repo, branch, default_name)
            origin = ov.git("remote", "get-url", "origin", cwd=root)
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "workspace"
                ov.git("clone", "--no-checkout", "--", origin, str(work), cwd=root)
                # Preserve identity without copying credential configuration.
                for key, value in identity.items():
                    ov.git("config", key, value, cwd=work)
                tip = ov.git("rev-parse", f"origin/{default_name}", cwd=work)
                old = ov.git(
                    "ls-remote", "--heads", "origin", f"refs/heads/{branch}", cwd=root
                ).split()
                old_head = old[0] if old else ""
                if pr and old_head != pr["headRefOid"]:
                    raise ov.SyncError("Sync branch changed while reading it; retry.")
                # A branch pushed before PR creation is replaceable; anything else
                # on the reserved name may be someone's work.
                if (
                    old_head
                    and not pr
                    and not owned_branch(work, tip, old_head, prefix)
                ):
                    raise ov.SyncError(
                        f"The reserved branch {branch} has commits sync did not create; move it aside before retrying."
                    )
                if pr and LABEL not in {x["name"] for x in pr["labels"]}:
                    gh(
                        root,
                        "api",
                        f"repos/{repo}/issues/{pr['number']}/labels",
                        payload={"labels": [LABEL]},
                    )
                ov.git("checkout", "--detach", (old_head if pr else tip), cwd=work)
                # Never merge or commit files outside the linked paper directory.
                if old_head and pr:
                    ancestor = ov.git("merge-base", tip, old_head, cwd=work)
                    outside = ov.git(
                        "diff", "--name-only", ancestor, old_head, cwd=work
                    ).splitlines()
                    if any(not name.startswith(prefix) for name in outside):
                        raise ov.SyncError(
                            "Sync branch changes files outside the paper; resolve it manually."
                        )
                    # Unrelated default-branch work does not invalidate this head's
                    # checks. Refresh only changed paper or GitHub's required base.
                    if ov.tree(work, ancestor, prefix) != ov.tree(
                        work, tip, prefix
                    ) or pr["mergeStateStatus"] in {"BEHIND", "DIRTY"}:
                        merge = subprocess.run(
                            ["git", "merge", "--no-commit", "--no-ff", tip],
                            cwd=work,
                            env=ov.git_environment(),
                            capture_output=True,
                        )
                        if merge.returncode:
                            paths = ov.git(
                                "diff", "--name-only", "--diff-filter=U", cwd=work
                            ).splitlines()
                            if paths:
                                raise ov.SyncError(
                                    conflict_message(work, tip, paths, pr["url"])
                                )
                            raise ov.SyncError(
                                "Could not merge the workspace base; check Git merge configuration and retry."
                            )
                        if (work / ".git/MERGE_HEAD").exists():
                            ov.git(
                                "commit",
                                "-m",
                                "Merge current workspace paper into Overleaf sync",
                                cwd=work,
                            )
                before = ov.load_config(work / prefix)
                if not before:
                    raise ov.SyncError(
                        "The sync branch removed overleaf.json; restore the linked paper configuration before retrying."
                    )
                if before.get("url") != config["url"]:
                    raise ov.SyncError(
                        "The default branch changed the linked Overleaf project; update this checkout and retry."
                    )
                marked = conflict_files(work, prefix)
                if marked:
                    raise ov.SyncError(
                        conflict_message(
                            work,
                            tip,
                            [prefix + name for name in marked],
                            pr["url"] if pr else "a paper PR",
                        )
                    )
                conflicted = pull_into(work, directory)
                after = ov.load_config(work / prefix)
                changed = bool(ov.git("status", "--porcelain", "--", prefix, cwd=work))
                if changed and only_recorded_base_changed(work, prefix, before, after):
                    ov.git("restore", "--", prefix + ov.CONFIG, cwd=work)
                    changed = False
                if changed:
                    ov.git("add", "--", prefix, cwd=work)
                    refuse_build_configs(
                        changed_paths(work, "--cached", "HEAD", "--", prefix)
                    )
                    authors = credits(work, before, after["base"])
                    message = "Sync Overleaf paper\n\n" + "\n".join(
                        f"Co-authored-by: {author}" for author in authors
                    )
                    ov.git("commit", "-m", message, cwd=work)
                head = ov.git("rev-parse", "HEAD", cwd=work)
                differs = ov.tree(work, tip, prefix) != ov.tree(work, head, prefix)
                if differs or pr:
                    final_paths = changed_paths(
                        work, ov.git("merge-base", tip, head, cwd=work), head
                    )
                    if any(not name.startswith(prefix) for name in final_paths):
                        raise ov.SyncError(
                            "A hook or branch changed files outside the paper; nothing pushed."
                        )
                    refuse_build_configs(final_paths)
                    if head != old_head:
                        ov.git(
                            "push",
                            f"--force-with-lease=refs/heads/{branch}:{old_head}",
                            "origin",
                            f"{head}:refs/heads/{branch}",
                            cwd=work,
                        )
                    if not pr:
                        created = gh(
                            root,
                            "api",
                            f"repos/{repo}/pulls",
                            payload={
                                "title": "Sync Overleaf paper",
                                "body": DEFAULT_BODY,
                                "head": branch,
                                "base": default_name,
                            },
                        )
                        # Keep the newly created PR available for reporting even if
                        # labeling fails; the next run repairs its missing label.
                        pr = created
                        gh(
                            root,
                            "api",
                            f"repos/{repo}/issues/{created['number']}/labels",
                            payload={"labels": [LABEL]},
                        )
                        pr = gh(
                            root,
                            "pr",
                            "view",
                            str(created["number"]),
                            "--repo",
                            repo,
                            "--json",
                            FIELDS,
                        )
                    marked = conflict_files(work, prefix)
                    if conflicted or marked:
                        raise ov.SyncError(
                            conflict_message(
                                work,
                                tip,
                                [prefix + name for name in marked]
                                or ov.git(
                                    "diff", "--name-only", "--diff-filter=U", cwd=work
                                ).splitlines()
                                or [prefix.rstrip("/")],
                                pr["url"],
                            )
                        )
                    # New edits or a refreshed base always need their own checks and
                    # a later quiet run; never merge a just-created/updated head.
                    if changed or head != old_head:
                        reset_status(root, repo, pr)
                        click.echo(
                            f"Updated {pr['url']}; waiting for checks and a run with no new Overleaf edits."
                        )
                        return
                    pr = gh(
                        root,
                        "pr",
                        "view",
                        str(pr["number"]),
                        "--repo",
                        repo,
                        "--json",
                        FIELDS,
                    )
                    if (
                        pr["headRefOid"] != head
                        or pr["mergeable"] != "MERGEABLE"
                        or pr["mergeStateStatus"] != "CLEAN"
                        or not checks_pass(pr)
                    ):
                        report(
                            root,
                            repo,
                            project_id,
                            waiting_message(pr, head),
                            pr,
                        )
                        click.echo(f"Waiting on {pr['url']}.")
                        return
                    # Derive squash credits from Overleaf's Git authors across the
                    # entire imported range, never from workspace commit bodies.
                    default_config = json.loads(
                        ov.git("show", f"{tip}:{prefix}{ov.CONFIG}", cwd=work)
                    )
                    authors = credits(work, default_config, after["base"])
                    trailers = {f"Co-authored-by: {author}" for author in authors}
                    # Re-check the exact head being merged, independent of the
                    # earlier branch-update path.
                    refuse_build_configs(
                        changed_paths(
                            work, ov.git("merge-base", tip, head, cwd=work), head
                        )
                    )
                    ov.require_expected_tip(work, tip, f"refs/heads/{default_name}")
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".md") as body:
                        body.write("\n".join(sorted(trailers)) + "\n")
                        body.flush()
                        gh(
                            root,
                            "pr",
                            "merge",
                            str(pr["number"]),
                            "--repo",
                            repo,
                            "--squash",
                            "--match-head-commit",
                            head,
                            "--subject",
                            "Sync Overleaf paper",
                            "--body-file",
                            body.name,
                        )
                    # Publication failures now belong on an open issue, not the
                    # closed sync PR.
                    pr = None
                    ov.git("fetch", "origin", default_name, cwd=work)
                    tip = ov.git("rev-parse", "FETCH_HEAD", cwd=work)
                    ov.git("checkout", "--detach", tip, cwd=work)
                click.get_current_context().invoke(
                    ov.publish,
                    project=work,
                    directory=directory,
                    dry_run=False,
                    expected_commit=tip,
                )
                issues = gh(
                    root,
                    "api",
                    f"repos/{repo}/issues?state=open&labels={LABEL}&per_page=100",
                )
                for issue in issues:
                    if issue[
                        "title"
                    ] == f"Overleaf sync needs attention ({project_id})" and MARKER in (
                        issue.get("body") or ""
                    ):
                        gh(
                            root,
                            "api",
                            f"repos/{repo}/issues/{issue['number']}",
                            "--method",
                            "PATCH",
                            payload={"state": "closed"},
                        )
                click.echo("Overleaf sync complete.")
        except ov.SyncError as exc:
            try:
                target = None if isinstance(exc, BuildConfigError) else pr
                report(root, repo, project_id, exc.format_message(), target)
            except ov.SyncError:
                click.echo(
                    "Could not report the sync failure on GitHub; the original refusal follows.",
                    err=True,
                )
            raise
