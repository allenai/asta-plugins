"""Find papers whose pairing record turns on scheduled sync, and sync each one."""

import base64
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

import click

from . import overleaf as ov


def scheduled(record: bytes | None) -> bool:
    """Whether a committed pairing record sets `"schedule": true`."""
    try:
        return record is not None and json.loads(record).get("schedule") is True
    except (ValueError, AttributeError):
        return False


def scheduled_directories(root: Path) -> list[str]:
    """Paper directories in a checkout whose committed record turns on the schedule."""
    return [
        directory
        for directory in ov.paired_directories(root)
        if scheduled(ov.tracked_record(root, directory))
    ]


def is_checkout(path: Path) -> bool:
    return (path / ".git").exists()


def local_checkouts(project: Path) -> list[Path]:
    """The project itself when it is a checkout, else the checkouts directly inside it."""
    if is_checkout(project):
        return [project]
    return sorted(
        child for child in project.iterdir() if child.is_dir() and is_checkout(child)
    )


_RAISE = object()


def gh_json(*args: str, not_found=_RAISE, timeout=90, lines=False):
    """Run gh for discovery and parse its JSON (one value per line with lines);
    return not_found on HTTP 404."""
    env = ov.git_environment()
    env.update(GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    try:
        result = subprocess.run(
            ["gh", *args],
            env=env,
            capture_output=True,
            timeout=timeout,
            **ov.no_terminal(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ov.SyncError(f"gh {args[0]} failed: {exc}") from None
    if result.returncode:
        error = result.stderr.decode(errors="replace").strip()
        if not_found is not _RAISE and "HTTP 404" in error:
            return not_found
        raise ov.SyncError(f"gh {args[0]} failed: {error or result.returncode}")
    try:
        if lines:
            return [json.loads(line) for line in result.stdout.splitlines() if line]
        return json.loads(result.stdout)
    except ValueError:
        raise ov.SyncError(f"gh {args[0]} returned invalid JSON") from None


def repo_scheduled(name: str, branch: str) -> bool:
    """Whether a repo's default branch commits a record that turns on the schedule."""
    # Listing only the records subtree keeps the response small and complete.
    tree = gh_json(
        "api", f"repos/{name}/git/trees/{branch}:{ov.RECORDS}?recursive=1", not_found={}
    )
    if tree.get("truncated"):
        raise ov.SyncError("the pairing-record listing was truncated")
    for entry in tree.get("tree", []):
        if entry.get("type") != "blob" or not entry["path"].endswith(".json"):
            continue
        blob = gh_json("api", f"repos/{name}/git/blobs/{entry['sha']}")
        if blob.get("encoding") == "base64" and scheduled(
            base64.b64decode(blob.get("content", ""))
        ):
            return True
    return False


# `gh repo list` caps filtered listings at 1,000 repos, so page through GraphQL.
REPOSITORIES_QUERY = """
query($login: String!, $endCursor: String) {
  repositoryOwner(login: $login) {
    repositories(first: 100, after: $endCursor, isFork: false) {
      nodes { nameWithOwner isArchived defaultBranchRef { name } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def owner_repos(owner: str) -> list[tuple[str, str | None]]:
    """(repo, None) for each unarchived source repo of a user or org that commits a
    scheduled record, and (repo, error) for each whose records could not be read."""
    try:
        listed = gh_json(
            "api",
            "graphql",
            "--paginate",
            "-f",
            f"query={REPOSITORIES_QUERY}",
            "-F",
            f"login={owner}",
            "--jq",
            ".data.repositoryOwner.repositories.nodes[] | select(.isArchived | not)",
            lines=True,
            # One call pages through every repo; a large org takes minutes.
            timeout=1800,
        )
    except ov.SyncError as exc:
        raise ov.SyncError(
            f"Cannot list {owner}'s repositories ({exc.message}); "
            "check gh authentication and the owner name."
        ) from None
    found = []
    for repo in listed:
        branch = (repo.get("defaultBranchRef") or {}).get("name")
        if not branch:
            continue
        name = repo["nameWithOwner"]
        try:
            if repo_scheduled(name, branch):
                found.append((name, None))
        except ov.SyncError as exc:
            found.append((name, f"cannot read pairing records: {exc.message}"))
    return found


@contextmanager
def github_credentials():
    """Let every Git call, including sync's temporary clones, use gh's token."""
    previous = os.environ.get("GIT_CONFIG_GLOBAL")
    original = previous or str(Path.home() / ".gitconfig")
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "gitconfig"
        config.write_text(
            f"[include]\n\tpath = {json.dumps(original)}\n"
            '[credential "https://github.com"]\n'
            "\thelper =\n"
            "\thelper = !gh auth git-credential\n"
        )
        os.environ["GIT_CONFIG_GLOBAL"] = str(config)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("GIT_CONFIG_GLOBAL", None)
            else:
                os.environ["GIT_CONFIG_GLOBAL"] = previous


def clone(name: str, dest: Path) -> Path:
    ov.git("clone", "--quiet", "--", f"https://github.com/{name}.git", str(dest))
    return dest


def scheduled_papers(project: Path, owner: str | None, workdir: Path):
    """Yield (label, checkout, paper directory) for each scheduled paper found.

    A checkout that cannot be cloned or read yields (label, None, error message).
    """
    if owner is None:
        checkouts = [
            (str(path), lambda path=path: path) for path in local_checkouts(project)
        ]
    else:
        checkouts = []
        for name, error in owner_repos(owner):
            if error:
                yield name, None, error
                continue
            checkouts.append(
                (name, lambda name=name: clone(name, workdir / name.replace("/", "__")))
            )
    for label, get in checkouts:
        try:
            root = get()
            directories = scheduled_directories(root)
        except click.ClickException as exc:
            yield label, None, exc.format_message()
            continue
        for directory in directories:
            yield label, root, directory
