"""Runner-independent, opt-in live release gate for Overleaf sync."""

import hashlib
import re
import tempfile
from pathlib import Path

import click

from asta import __version__

from . import overleaf as ov
from . import overleaf_sync as sync
from .overleaf_check import check_workspace


def require_release_check(project: Path, directory: str, check_repo: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", check_repo) or any(
        not part.strip(".") for part in check_repo.split("/")
    ):
        raise ov.SyncError("The check repository must be owner/name; syncing nothing.")
    root, paper, _ = ov.resolve(project, directory)
    try:
        target = sync.gh(root, "repo", "view", "--json", "nameWithOwner")
        scratch = sync.gh(root, "repo", "view", check_repo, "--json", "nameWithOwner")
    except click.ClickException as exc:
        raise ov.SyncError(
            f"Overleaf check failed (pair access/setup): cannot reach GitHub pair: {exc}; syncing nothing."
        ) from exc
    if target["nameWithOwner"].lower() == scratch["nameWithOwner"].lower():
        raise ov.SyncError(
            "The check repository is the paper being synced; syncing nothing."
        )

    # Canonical identities also catch renamed repositories and redirects.
    url = f"https://github.com/{scratch['nameWithOwner']}.git"
    version_key = hashlib.sha256(__version__.encode()).hexdigest()
    ref = f"refs/tags/asta-overleaf-check/{version_key}"
    try:
        cached = ov.git("ls-remote", "--refs", url, ref, cwd=root)
    except click.ClickException as exc:
        raise ov.SyncError(
            f"Overleaf check failed (pair access/setup): cannot read pass record: {exc}; syncing nothing."
        ) from exc
    if cached:
        click.echo(f"Overleaf check already passed for asta {__version__}.")
        return

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "check"
        try:
            ov.git("clone", "-q", "--", url, str(work), cwd=root)
            for key in ("user.name", "user.email"):
                ov.git(
                    "config", key, ov.git("config", "--get", key, cwd=root), cwd=work
                )
            config = ov.load_config(work / "paper")
            if not config:
                raise ov.SyncError(
                    "The scratch repository has no paired Overleaf project."
                )
            target_config = ov.load_config(paper)
            if target_config and config["url"] == target_config["url"]:
                raise ov.SyncError(
                    "The scratch project is the paper's Overleaf project."
                )
            commit = ov.git("rev-parse", "HEAD", cwd=work)
        except click.ClickException as exc:
            raise ov.SyncError(
                f"Overleaf check failed (pair access/setup): {exc}; syncing nothing."
            ) from exc
        # The check owns its entire round trip, waits for PR checks, restores both
        # sides, and raises on any cleanup failure. Its internal syncs opt out.
        check_workspace(work, "paper", 600)
        try:
            ov.git("push", "-q", "origin", f"{commit}:{ref}", cwd=work)
        except click.ClickException as exc:
            raise ov.SyncError(
                f"Overleaf check passed but could not record the pass: {exc}; syncing nothing."
            ) from exc
    click.echo(f"Overleaf check recorded PASS for asta {__version__}.")
