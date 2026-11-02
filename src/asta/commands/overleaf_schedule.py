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


def gh_json(*args: str):
    """Run gh for discovery; None on failure, so one unreadable repo is skipped."""
    env = ov.git_environment()
    env.update(GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    try:
        result = subprocess.run(
            ["gh", *args], env=env, capture_output=True, timeout=90, **ov.no_terminal()
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def owner_repos(owner: str) -> list[str]:
    """Unarchived source repos of a user or org that commit a scheduled record."""
    listed = gh_json(
        "repo",
        "list",
        owner,
        "--source",
        "--no-archived",
        "--limit",
        "1000",
        "--json",
        "nameWithOwner,defaultBranchRef",
    )
    if listed is None:
        raise ov.SyncError(
            f"Cannot list {owner}'s repositories; check gh authentication and the owner name."
        )
    found = []
    for repo in listed:
        branch = (repo.get("defaultBranchRef") or {}).get("name")
        if not branch:
            continue
        name = repo["nameWithOwner"]
        tree = gh_json("api", f"repos/{name}/git/trees/{branch}?recursive=1")
        records = [
            entry["path"]
            for entry in (tree or {}).get("tree", [])
            if entry.get("type") == "blob"
            and entry["path"].startswith(f"{ov.RECORDS}/")
            and entry["path"].endswith(".json")
        ]
        for path in records:
            content = gh_json("api", f"repos/{name}/contents/{path}?ref={branch}")
            raw = None
            if isinstance(content, dict) and content.get("encoding") == "base64":
                raw = base64.b64decode(content.get("content", ""))
            if scheduled(raw):
                found.append(name)
                break
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
        checkouts = [
            (name, lambda name=name: clone(name, workdir / name.replace("/", "__")))
            for name in owner_repos(owner)
        ]
    for label, get in checkouts:
        try:
            root = get()
            directories = scheduled_directories(root)
        except click.ClickException as exc:
            yield label, None, exc.format_message()
            continue
        for directory in directories:
            yield label, root, directory
