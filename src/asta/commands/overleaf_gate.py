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


def require_release_check(
    project: Path, directory: str, check_repo: str, timeout: int = 600
):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", check_repo) or any(
        not part.strip(".") for part in check_repo.split("/")
    ):
        raise ov.SyncError("The check repository must be owner/name; syncing nothing.")
    root, paper, _ = ov.resolve(project, directory)
    try:
        target_config = ov.load_config(paper)
        if not target_config:
            raise ov.SyncError(
                "Import and commit the paper with overleaf pull before scheduling sync."
            )
        target_id = ov.validate_url(target_config["url"]).rsplit("/", 1)[1]
    except click.ClickException as exc:
        raise ov.SyncError(
            f"Overleaf check failed (pair access/setup): {exc}; syncing nothing."
        ) from exc
    try:
        target = sync.gh(root, "repo", "view", "--json", "nameWithOwner,url")
        host_url = target["url"].rsplit("/", 2)[0]
        scratch = sync.gh(
            root,
            "repo",
            "view",
            f"{host_url}/{check_repo}",
            "--json",
            "nameWithOwner,url,sshUrl",
        )
    except click.ClickException as exc:
        raise ov.SyncError(
            f"Overleaf check failed (pair access/setup): cannot reach GitHub pair: {exc}; syncing nothing."
        ) from exc
    if target["nameWithOwner"].lower() == scratch["nameWithOwner"].lower():
        raise ov.SyncError(
            "The check repository is the paper being synced; syncing nothing."
        )

    # Canonical identities also catch renamed repositories and redirects.
    origin = ov.git("remote", "get-url", "origin", cwd=root)
    url = (
        scratch["sshUrl"]
        if origin.startswith(("git@", "ssh://"))
        else scratch["url"] + ".git"
    )
    version_key = hashlib.sha256(__version__.encode()).hexdigest()
    ref = f"refs/tags/asta-overleaf-check/{version_key}"
    try:
        cached = ov.git("ls-remote", "--refs", url, ref, cwd=root)
    except click.ClickException as exc:
        raise ov.SyncError(
            f"Overleaf check failed (pair access/setup): cannot read pass record: {exc}; syncing nothing."
        ) from exc
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "check"
        try:
            ov.git("clone", "-q", "--", url, str(work), cwd=root)
            config = ov.load_config(work / "paper")
            if not config:
                raise ov.SyncError(
                    "The scratch repository has no paired Overleaf project."
                )
            scratch_id = ov.validate_url(config["url"]).rsplit("/", 1)[1]
            if scratch_id.casefold() == target_id.casefold():
                raise ov.SyncError(
                    "The scratch project is the paper's Overleaf project."
                )
            # Pair isolation is checked even when this version already passed:
            # a repository can be re-paired after the pass was recorded.
            if cached:
                click.echo(f"Overleaf check already passed for asta {__version__}.")
                return
            for key in ("user.name", "user.email"):
                ov.git(
                    "config", key, ov.git("config", "--get", key, cwd=root), cwd=work
                )
            commit = ov.git("rev-parse", "HEAD", cwd=work)
        except click.ClickException as exc:
            raise ov.SyncError(
                f"Overleaf check failed (pair access/setup): {exc}; syncing nothing."
            ) from exc
        # The check owns its entire round trip and waits for PR checks; a busy
        # pair raises PairBusy, which also syncs nothing.
        check_workspace(work, "paper", timeout)
        try:
            ov.git("push", "-q", "origin", f"{commit}:{ref}", cwd=work)
        except click.ClickException as exc:
            raise ov.SyncError(
                f"Overleaf check passed but could not record the pass: {exc}; syncing nothing."
            ) from exc
    click.echo(f"Overleaf check recorded PASS for asta {__version__}.")
