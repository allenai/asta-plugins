"""Runner-independent, serialized Overleaf synchronization through a GitHub PR."""

import json
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import click

from . import overleaf as ov

LABEL = "asta:overleaf-sync"
MARKER = "<!-- asta-overleaf-sync -->"
FIELDS = "number,url,headRefOid,baseRefName,body,labels,mergeable,mergeStateStatus,statusCheckRollup"


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
    try:
        yield True
    finally:
        ov.git(
            "push", f"--force-with-lease={ref}:{owner}", "origin", f":{ref}", cwd=root
        )


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


def conflict_files(root: Path, prefix: str):
    return sorted(
        name
        for name, data in ov.paper_files(root, "HEAD", prefix).items()
        if Path(name).suffix.lower() in ov.MERGE_SUFFIXES
        and b"\0" not in data
        and (ov.MARKER.search(data) or ov.re.search(rb"(?m)^=======\r?$", data))
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
            for x in authors.splitlines()
            if "<" in x and ">" in x and not any(c in x for c in "\r\0")
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


def sync_workspace(project: Path, directory: str):
    root, paper, prefix = ov.resolve(project, directory)
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
    with lock(root, project_id) as acquired:
        if not acquired:
            click.echo(
                "Overleaf sync is already running (or its interrupted run needs lock recovery)."
            )
            return
        pr = None
        try:
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
            if len(prs) > 1:
                raise ov.SyncError(
                    "Multiple sync PRs exist; close the duplicate before retrying."
                )
            pr = prs[0] if prs else None
            if pr and (
                MARKER not in pr["body"]
                or LABEL not in {x["name"] for x in pr["labels"]}
                or pr["baseRefName"] != default_name
            ):
                raise ov.SyncError(
                    "The reserved sync branch has an unrelated PR; move it aside before retrying."
                )
            origin = ov.git("remote", "get-url", "origin", cwd=root)
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "workspace"
                ov.git("clone", "--no-checkout", "--", origin, str(work), cwd=root)
                # Preserve the caller's Git identity without copying credential config.
                for key in ("user.name", "user.email"):
                    value = ov.git("config", "--get", key, cwd=root)
                    ov.git("config", key, value, cwd=work)
                tip = ov.git("rev-parse", f"origin/{default_name}", cwd=work)
                old = ov.git(
                    "ls-remote", "--heads", "origin", f"refs/heads/{branch}", cwd=root
                ).split()
                old_head = old[0] if old else ""
                if pr and old_head != pr["headRefOid"]:
                    raise ov.SyncError("Sync branch changed while reading it; retry.")
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
                    merge = subprocess.run(
                        ["git", "merge", "--no-commit", "--no-ff", tip],
                        cwd=work,
                        env=ov.git_environment(),
                        capture_output=True,
                    )
                    if merge.returncode:
                        raise ov.SyncError(
                            f"The sync PR conflicts with workspace commit {tip}; its author must resolve it in the sync PR."
                        )
                    if (work / ".git/MERGE_HEAD").exists():
                        ov.git(
                            "commit",
                            "-m",
                            "Merge current workspace paper into Overleaf sync",
                            cwd=work,
                        )
                before = ov.load_config(work / prefix)
                if before.get("url") != config["url"]:
                    raise ov.SyncError(
                        "The default branch changed the linked Overleaf project; update this checkout and retry."
                    )
                marked = conflict_files(work, prefix)
                if marked:
                    raise ov.SyncError(
                        "Resolve conflict markers in the sync PR: " + ", ".join(marked)
                    )
                conflicted = pull_into(work, directory)
                after = ov.load_config(work / prefix)
                changed = bool(ov.git("status", "--porcelain", "--", prefix, cwd=work))
                if changed and only_recorded_base_changed(work, prefix, before, after):
                    ov.git("restore", "--", prefix + ov.CONFIG, cwd=work)
                    changed = False
                if changed:
                    ov.git("add", "--", prefix, cwd=work)
                    authors = credits(work, before, after["base"])
                    message = "Sync Overleaf paper\n\n" + "\n".join(
                        f"Co-authored-by: {author}" for author in authors
                    )
                    ov.git("commit", "-m", message, cwd=work)
                head = ov.git("rev-parse", "HEAD", cwd=work)
                differs = ov.tree(work, tip, prefix) != ov.tree(work, head, prefix)
                if differs or pr:
                    final_paths = ov.git(
                        "diff", "--name-only", tip, head, cwd=work
                    ).splitlines()
                    if any(not name.startswith(prefix) for name in final_paths):
                        raise ov.SyncError(
                            "A hook or branch changed files outside the paper; nothing pushed."
                        )
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
                                "body": MARKER
                                + "\n\nImport co-author edits before publishing the default branch.",
                                "head": branch,
                                "base": default_name,
                            },
                        )
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
                    if conflicted or conflict_files(work, prefix):
                        culprit = ov.git(
                            "log", "-1", "--format=%H", tip, "--", prefix, cwd=work
                        )
                        raise ov.SyncError(
                            f"Overleaf edits conflict with workspace commit {culprit}; that change's author must resolve the markers in {pr['url']}."
                        )
                    # New edits or a refreshed base always need their own checks and
                    # a later quiet run; never merge a just-created/updated head.
                    if changed or head != old_head:
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
                            "Sync PR is waiting for successful checks and conflict resolution; a person must resolve failing checks or conflicts.",
                            pr,
                        )
                        click.echo(f"Waiting on {pr['url']}.")
                        return
                    # Preserve every carried author across the squash, including
                    # earlier updates and human resolutions on this same PR.
                    log = ov.git(
                        "log", "--format=%aN <%aE>%n%B", f"{tip}..{head}", cwd=work
                    )
                    trailers = {
                        line
                        for line in log.splitlines()
                        if line.startswith("Co-authored-by: ")
                    }
                    authors = ov.git(
                        "log", "--format=%aN <%aE>", f"{tip}..{head}", cwd=work
                    ).splitlines()
                    trailers.update(f"Co-authored-by: {a}" for a in authors)
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
            report(root, repo, project_id, exc.format_message(), pr)
            raise
