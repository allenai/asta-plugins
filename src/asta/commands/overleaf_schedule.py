"""Find papers whose pairing record turns on scheduled sync, and sync each one."""

import base64
import binascii
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

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


_RAISE = object()


def gh_json(*args: str, not_found=_RAISE, timeout=90):
    """Run gh for discovery and parse its JSON; return not_found on HTTP 404."""
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
    except (OSError, subprocess.TimeoutExpired):
        raise ov.SyncError(
            "GitHub discovery request could not run; retry after checking gh and network access."
        ) from None
    if result.returncode:
        error = result.stderr.decode(errors="replace").strip()
        if not_found is not _RAISE and "HTTP 404" in error:
            return not_found
        # Transport diagnostics can contain credentials; report the repo separately.
        raise ov.SyncError(
            "GitHub discovery request failed; check gh authentication and repository access, then retry."
        )
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise ov.SyncError(
            "GitHub discovery returned invalid JSON; retry the request."
        ) from None


def record_scheduled(name: str, path: str) -> bool:
    """Whether a repo's default branch commits this record with the schedule on."""
    blob = gh_json("api", f"repos/{name}/contents/{quote(path)}", not_found={})
    if not blob:
        return False  # Deleted since the search index saw it.
    try:
        if blob.get("encoding") != "base64":
            raise ValueError
        raw = base64.b64decode("".join(blob["content"].split()), validate=True)
    except (KeyError, ValueError, binascii.Error):
        raise ov.SyncError(
            f"GitHub returned an unreadable pairing record: {path}; retry discovery."
        ) from None
    return scheduled(raw)


def owner_repos(owner: str) -> list[tuple[str, str | None]]:
    """(repo, None) for each repo of a user or org that commits a scheduled record,
    plus (repo, error) for each candidate record that could not be read.

    One code search finds the candidates; the index can lag a fresh commit by a
    run, and each candidate's record is read to confirm it.
    """
    query = f"schedule in:file path:{ov.RECORDS} extension:json user:{owner}"
    try:
        pages = gh_json(
            "api",
            "--method",
            "GET",
            "search/code",
            "-f",
            f"q={query}",
            "-f",
            "per_page=100",
            "--paginate",
            "--slurp",
        )
    except ov.SyncError as exc:
        raise ov.SyncError(
            f"Cannot search {owner}'s repositories ({exc.message}); "
            "check gh authentication and the owner name."
        ) from None
    if any(page["incomplete_results"] for page in pages):
        raise ov.SyncError(
            f"GitHub code search for {owner} returned incomplete results; retry discovery."
        )
    if any(page["total_count"] > 1000 for page in pages):
        raise ov.SyncError(
            f"GitHub code search for {owner} exceeds GitHub's 1,000-result limit; "
            "not all scheduled papers can be discovered."
        )
    candidates: dict[str, list[str]] = {}
    for page in pages:
        for hit in page["items"]:
            path = hit["path"]
            if path.startswith(f"{ov.RECORDS}/") and path.endswith(".json"):
                candidates.setdefault(hit["repository"]["full_name"], []).append(path)
    found = []
    for name, paths in sorted(candidates.items()):
        enabled = False
        for path in paths:
            try:
                if record_scheduled(name, path):
                    enabled = True
            except ov.SyncError as exc:
                found.append(
                    (name, f"cannot read pairing record {path}: {exc.message}")
                )
        if enabled:
            found.append((name, None))
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
    dest.parent.mkdir(parents=True, exist_ok=True)
    ov.git(
        "clone",
        "--quiet",
        "--",
        f"https://github.com/{name}.git",
        str(dest),
        cwd=dest.parent,
    )
    return dest


def scheduled_papers(owner: str, workdir: Path):
    """Yield (repo, checkout, paper directory) for each scheduled paper found.

    A repo that cannot be cloned or read, for any reason, yields
    (repo, None, error message) so the run carries on to the next repo.
    """
    for name, error in owner_repos(owner):
        if error:
            yield name, None, error
            continue
        try:
            root = clone(name, workdir / name.replace("/", "__"))
            directories = scheduled_directories(root)
        except click.ClickException as exc:
            yield name, None, exc.format_message()
            continue
        except Exception as exc:
            yield name, None, f"unexpected {type(exc).__name__}"
            continue
        for directory in directories:
            yield name, root, directory
