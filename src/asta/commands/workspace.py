"""Fetch workspace build rules from the version selected by a project."""

import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import click

WORKFLOW = "allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@"
ASSET = "plugins/asta-tools/skills/workspace/assets/workspace.mk"
WORKFLOW_LINE = re.compile(
    r"^\s*uses:\s*['\"]?"
    + re.escape(WORKFLOW)
    + r"([A-Za-z0-9._/-]+)['\"]?(?:\s*(?:#.*)?)?$"
)
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_ASSET_BYTES = 1024 * 1024


def selected_ref(project: Path) -> str:
    workflow = project / ".github/workflows/docs.yml"
    try:
        lines = workflow.read_text().splitlines()
    except FileNotFoundError as exc:
        raise click.ClickException(f"Missing {workflow}") from exc
    refs = []
    for line in lines:
        if WORKFLOW not in line or line.lstrip().startswith("#"):
            continue
        match = WORKFLOW_LINE.fullmatch(line)
        if match is None:
            raise click.ClickException(
                f"Invalid asta-plugins workflow line in {workflow}"
            )
        refs.append(match.group(1))
    if len(refs) != 1:
        raise click.ClickException(
            f"Expected exactly one asta-plugins workspace workflow in {workflow}"
        )
    ref = refs[0]
    if (
        not re.fullmatch(r"[A-Za-z0-9._/-]+", ref)
        or ref.startswith("/")
        or any(part in ("", ".", "..") for part in ref.split("/"))
    ):
        raise click.ClickException(f"Invalid asta-plugins ref in {workflow}: {ref}")
    return ref


def archive_url(ref: str) -> str:
    if re.fullmatch(r"v\d+\.\d+\.\d+", ref):
        path = f"refs/tags/{ref}"
    elif ref in ("main", "latest"):
        path = f"refs/heads/{ref}"
    else:
        path = ref
    return f"https://github.com/allenai/asta-plugins/archive/{path}.tar.gz"


def load_asset(ref: str) -> tuple[bytes, bytes]:
    try:
        with urlopen(archive_url(ref), timeout=30) as response:
            archive = response.read(MAX_ARCHIVE_BYTES + 1)
    except (OSError, URLError) as exc:
        raise click.ClickException(
            f"Could not fetch asta-plugins@{ref}: {exc}"
        ) from exc
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise click.ClickException("Asta-plugins archive is too large")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            matches = [member for member in bundle if member.name.endswith("/" + ASSET)]
            if (
                len(matches) != 1
                or not matches[0].isfile()
                or matches[0].size > MAX_ASSET_BYTES
            ):
                raise click.ClickException(
                    f"asta-plugins@{ref} does not provide a valid {ASSET}"
                )
            stream = bundle.extractfile(matches[0])
            if stream is None:
                raise click.ClickException(
                    f"Cannot read {ASSET} from asta-plugins@{ref}"
                )
            result = stream.read(MAX_ASSET_BYTES + 1)
    except (tarfile.TarError, OSError) as exc:
        raise click.ClickException(f"Invalid asta-plugins archive: {exc}") from exc
    if not result or len(result) > MAX_ASSET_BYTES:
        raise click.ClickException(
            f"asta-plugins@{ref} has an empty or oversized {ASSET}"
        )
    return result, archive


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        temp_path = Path(tmp.name)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


@click.group()
def workspace() -> None:
    """Manage files supplied by the Asta workspace skill."""


@workspace.command()
@click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
@click.option(
    "--refresh",
    is_flag=True,
    help="Fetch again, including moving refs such as main and latest.",
)
def sync(project: Path, refresh: bool) -> None:
    """Load shared Makefile rules at the version selected in docs.yml."""
    project = project.resolve()
    if (project / "workspace.mk").exists():
        click.echo("workspace.mk exists in the project; keeping its local override")
        return
    ref = selected_ref(project)
    source_ref = os.environ.get("ASTA_WORKSPACE_RESOLVED_SHA") or ref
    if source_ref != ref and not re.fullmatch(r"[0-9a-fA-F]{40}", source_ref):
        raise click.ClickException(
            "ASTA_WORKSPACE_RESOLVED_SHA must be a full commit SHA"
        )
    cache = project / ".asta/cache"
    target = cache / "workspace.mk"
    manifest = cache / "workspace.json"
    if (
        (project / ".asta").is_symlink()
        or cache.is_symlink()
        or target.is_symlink()
        or manifest.is_symlink()
    ):
        raise click.ClickException("Workspace cache must not be a symlink")
    if (project / ".git").exists() and subprocess.run(
        ["git", "check-ignore", "-q", ".asta/cache/workspace.mk"],
        cwd=project,
        check=False,
    ).returncode != 0:
        raise click.ClickException(
            "Add .asta/cache/ to .gitignore before syncing workspace rules"
        )
    try:
        state = json.loads(manifest.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    archive_sha = state.get("archive_sha256")
    if not isinstance(archive_sha, str) or not re.fullmatch(
        r"[0-9a-f]{64}", archive_sha
    ):
        archive_sha = ""
    archive_path = cache / "archives" / archive_sha
    cache_valid = (
        target.is_file()
        and state.get("ref") == ref
        and state.get("source_ref") == source_ref
        and state.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest()
        and bool(archive_sha)
        and archive_path.is_file()
        and not archive_path.is_symlink()
        and archive_sha == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    )
    if cache_valid and not refresh:
        click.echo(f"workspace.mk already cached from asta-plugins@{ref}")
        return
    try:
        asset, archive = load_asset(source_ref)
    except click.ClickException:
        if cache_valid:
            click.echo(
                f"Could not refresh asta-plugins@{ref}; using the cached copy", err=True
            )
            return
        raise
    archive_sha = hashlib.sha256(archive).hexdigest()
    archive_path = cache / "archives" / archive_sha
    if not archive_path.is_file():
        _atomic_write(archive_path, archive)
    managed = (
        f"override ASTA_PLUGINS_REF := {ref}\n"
        f"override ASTA_WORKSPACE_ARCHIVE := .asta/cache/archives/{archive_sha}\n"
    ).encode() + asset
    _atomic_write(target, managed)
    _atomic_write(
        manifest,
        json.dumps(
            {
                "ref": ref,
                "source_ref": source_ref,
                "sha256": hashlib.sha256(managed).hexdigest(),
                "archive_sha256": archive_sha,
            },
            sort_keys=True,
        ).encode()
        + b"\n",
    )
    click.echo(f"Loaded workspace.mk from asta-plugins@{ref}")
