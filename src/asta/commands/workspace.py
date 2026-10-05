"""Fetch workspace build rules from the version selected by a project."""

import hashlib
import http.client
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

WORKFLOW = "/.github/workflows/workspace-quarto-site.yml@"
ASSET = "plugins/asta-tools/skills/workspace/assets/workspace.mk"
WORKFLOW_LINE = re.compile(
    r"^\s*uses:\s*(?P<quote>['\"]?)"
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    + re.escape(WORKFLOW)
    + r"(?P<ref>[A-Za-z0-9._/-]+)(?P=quote)(?:\s*(?:#.*)?)?$"
)
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ASSET_BYTES = 1024 * 1024


def selected_source(project: Path) -> tuple[str, str]:
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
        refs.append((match.group("repository"), match.group("ref")))
    if len(refs) != 1:
        raise click.ClickException(
            f"Expected exactly one asta-plugins workspace workflow in {workflow}"
        )
    repository, ref = refs[0]
    if any(part in (".", "..") for part in repository.split("/")):
        raise click.ClickException(f"Invalid workflow repository in {workflow}")
    if (
        not re.fullmatch(r"[A-Za-z0-9._/-]+", ref)
        or ref.startswith("/")
        or any(part in ("", ".", "..") for part in ref.split("/"))
    ):
        raise click.ClickException(f"Invalid asta-plugins ref in {workflow}: {ref}")
    return repository, ref


def archive_url(repository: str, ref: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{40}", ref):
        path = ref
    else:
        try:
            found = subprocess.run(
                [
                    "git",
                    "ls-remote",
                    "--heads",
                    "--tags",
                    f"https://github.com/{repository}.git",
                    f"refs/tags/{ref}",
                    f"refs/tags/{ref}^{{}}",
                    f"refs/heads/{ref}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise click.ClickException(f"Could not resolve asta-plugins@{ref}") from exc
        if found.returncode != 0:
            raise click.ClickException(f"Could not resolve asta-plugins@{ref}")
        refs = {}
        for line in found.stdout.splitlines():
            sha, _, name = line.partition("\t")
            if re.fullmatch(r"[0-9a-fA-F]{40}", sha):
                refs[name] = sha
        path = next(
            (
                refs[name]
                for name in (
                    f"refs/tags/{ref}^{{}}",
                    f"refs/tags/{ref}",
                    f"refs/heads/{ref}",
                )
                if name in refs
            ),
            "",
        )
        if not path:
            raise click.ClickException(f"Could not resolve asta-plugins@{ref}")
    return f"https://github.com/{repository}/archive/{path}.tar.gz"


def load_asset(repository: str, ref: str) -> tuple[bytes, bytes]:
    try:
        with urlopen(archive_url(repository, ref), timeout=30) as response:
            archive = response.read(MAX_ARCHIVE_BYTES + 1)
    except (OSError, URLError, http.client.HTTPException) as exc:
        raise click.ClickException(
            f"Could not fetch asta-plugins@{ref}: {exc}"
        ) from exc
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise click.ClickException("Asta-plugins archive is too large")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            matches = []
            total_bytes = 0
            for index, member in enumerate(bundle):
                if index >= 10000:
                    raise click.ClickException(
                        "Asta-plugins archive has too many entries"
                    )
                total_bytes += member.size
                if total_bytes > MAX_UNCOMPRESSED_BYTES:
                    raise click.ClickException("Asta-plugins archive expands too large")
                parts = member.name.split("/", 1)
                if len(parts) == 2 and parts[0] and parts[1] == ASSET:
                    matches.append(member)
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
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(data)
        temp_path.chmod(0o644)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
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
    repository, ref = selected_source(project)
    source_ref = os.environ.get("ASTA_WORKSPACE_RESOLVED_SHA") or ref
    resolved_repository = os.environ.get("ASTA_WORKSPACE_RESOLVED_REPOSITORY")
    if resolved_repository and resolved_repository.casefold() != repository.casefold():
        raise click.ClickException(
            f"Called workflow repository {resolved_repository} differs from {repository} in docs.yml"
        )
    repository = resolved_repository or repository
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
        or (cache / "archives").is_symlink()
        or target.is_symlink()
        or manifest.is_symlink()
    ):
        raise click.ClickException("Workspace cache must not be a symlink")
    try:
        inside_git = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise click.ClickException(
            "git is required to verify the workspace cache ignore rule"
        ) from exc
    if inside_git.returncode == 0 and inside_git.stdout.strip() == "true":
        tracked = subprocess.run(
            ["git", "-C", str(project), "ls-files", "--cached", "--", ".asta/cache"],
            capture_output=True,
            text=True,
            check=False,
        )
        if tracked.returncode != 0:
            raise click.ClickException(
                "Could not verify whether the workspace cache is tracked"
            )
        if tracked.stdout:
            raise click.ClickException(
                "Workspace cache is tracked by Git; remove it from the index with "
                "'git rm --cached -r .asta/cache' before syncing"
            )
        ignored = subprocess.run(
            [
                "git",
                "-C",
                str(project),
                "check-ignore",
                "-q",
                ".asta/cache/workspace.mk",
            ],
            check=False,
        )
        if ignored.returncode == 1:
            raise click.ClickException(
                "Add .asta/cache/ to .gitignore before syncing workspace rules"
            )
        if ignored.returncode != 0:
            raise click.ClickException(
                "Could not verify the workspace cache ignore rule"
            )
    elif not (
        inside_git.returncode == 128
        and "not a git repository" in inside_git.stderr.lower()
    ):
        raise click.ClickException("Could not determine whether the project is in Git")
    try:
        state = json.loads(manifest.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    archive_sha = state.get("archive_sha256")
    if not isinstance(archive_sha, str) or not re.fullmatch(
        r"[0-9a-f]{64}", archive_sha
    ):
        archive_sha = ""
    archive_path = cache / "archives" / archive_sha
    if archive_path.is_symlink():
        raise click.ClickException("Workspace source archive must not be a symlink")
    cache_valid = (
        target.is_file()
        and state.get("repository") == repository
        and state.get("ref") == ref
        and state.get("source_ref") == source_ref
        and state.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest()
        and bool(archive_sha)
        and archive_path.is_file()
        and not archive_path.is_symlink()
        and archive_sha == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    )
    if cache_valid and not refresh:
        target.touch()
        if not re.fullmatch(r"[0-9a-fA-F]{40}", ref):
            click.echo(
                f"Using cached {ref}; run 'asta workspace sync --refresh' to update",
                err=True,
            )
        click.echo(f"workspace.mk already cached from asta-plugins@{ref}")
        return
    try:
        asset, archive = load_asset(repository, source_ref)
    except click.ClickException:
        if cache_valid:
            target.touch()
            click.echo(
                f"Could not refresh asta-plugins@{ref}; using the cached copy", err=True
            )
            return
        raise
    archive_sha = hashlib.sha256(archive).hexdigest()
    archive_path = cache / "archives" / archive_sha
    if archive_path.is_symlink():
        raise click.ClickException("Workspace source archive must not be a symlink")
    if (
        not archive_path.is_file()
        or hashlib.sha256(archive_path.read_bytes()).hexdigest() != archive_sha
    ):
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
                "repository": repository,
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
