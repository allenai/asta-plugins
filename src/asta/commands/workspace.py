"""Fetch workspace build rules from the version selected by a project."""

import hashlib
import http.client
import io
import json
import os
import re
import signal
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import click

WORKFLOW = "/.github/workflows/workspace-quarto-site.yml@"
ASSET = "plugins/asta-tools/skills/workspace/assets/workspace.mk"
ASSET_DIR = "plugins/asta-tools/skills/workspace/assets/"
# Scripts workspace.mk runs; a committed scripts/<name> takes precedence.
CHECK_SCRIPTS = ("quarto-check.sh", "wait-for-preview.sh")
VIEWER_SCRIPTS = ("paper-discovery.py", "paper-viewer.py")
SCRIPTS = CHECK_SCRIPTS + VIEWER_SCRIPTS
MANAGED_SCRIPTS_MARKER = b"ASTA_WORKSPACE_MANAGED_SCRIPTS := 1"
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
    if not refs or len(set(refs)) != 1:
        raise click.ClickException(
            f"Expected one asta-plugins workspace source in {workflow}"
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


def load_scripts(archive: bytes) -> dict[str, bytes]:
    wanted = {ASSET_DIR + name: name for name in SCRIPTS}
    scripts: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            for member in bundle:
                parts = member.name.split("/", 1)
                name = wanted.get(parts[1]) if len(parts) == 2 and parts[0] else None
                if name is None:
                    continue
                stream = bundle.extractfile(member) if member.isfile() else None
                if name in scripts or stream is None or member.size > MAX_ASSET_BYTES:
                    raise click.ClickException(
                        f"Invalid {name} in asta-plugins archive"
                    )
                data = stream.read(MAX_ASSET_BYTES + 1)
                if not data or len(data) > MAX_ASSET_BYTES:
                    raise click.ClickException(f"Empty or oversized {name} in archive")
                scripts[name] = data
    except (tarfile.TarError, OSError) as exc:
        raise click.ClickException(f"Invalid asta-plugins archive: {exc}") from exc
    # Older refs can omit scripts; only the Make target that needs one should fail.
    return scripts


def _script_hashes(scripts: dict[str, bytes]) -> dict[str, str]:
    return {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(scripts.items())
    }


def _require_scripts(rules: bytes, scripts: Mapping[str, object], ref: str) -> None:
    required = set(CHECK_SCRIPTS)
    if re.search(rb"^workspace-viewers\s*:", rules, re.MULTILINE):
        required.update(VIEWER_SCRIPTS)
    if MANAGED_SCRIPTS_MARKER not in rules.splitlines() or required - scripts.keys():
        raise click.ClickException(
            f"asta-plugins@{ref} does not support all managed workspace scripts; "
            "keep the project scripts or select a newer ref in docs.yml"
        )


def _scripts_state(directory: Path, names: dict[str, str]) -> dict[str, str] | None:
    state = {}
    for name in names:
        if name not in SCRIPTS:
            return None
        path = directory / name
        if path.is_symlink() or not path.is_file():
            return None
        state[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


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
@click.option(
    "--require-scripts",
    is_flag=True,
    help="Verify all scripts required by the selected rules before removing project copies.",
)
def sync(project: Path, refresh: bool, require_scripts: bool) -> None:
    """Load shared Makefile rules at the version selected in docs.yml."""
    project = project.resolve()
    if (project / "workspace.mk").exists():
        if require_scripts:
            raise click.ClickException(
                "Local workspace.mk overrides managed rules; keep its project scripts"
            )
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
    scripts_dir = cache / "scripts"
    if scripts_dir.is_symlink() or (
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
    )
    cached_archive = archive_path.read_bytes() if cache_valid else b""
    cache_valid = (
        cache_valid and archive_sha == hashlib.sha256(cached_archive).hexdigest()
    )
    scripts_dir = scripts_dir / archive_sha if archive_sha else scripts_dir
    if scripts_dir.is_symlink():
        raise click.ClickException("Workspace scripts directory must not be a symlink")
    scripts_header = (
        f"override ASTA_WORKSPACE_SCRIPTS := .asta/cache/scripts/{archive_sha}\n"
    ).encode()
    if cache_valid and (
        not isinstance(state.get("scripts"), dict)
        or state["scripts"] != _scripts_state(scripts_dir, state["scripts"])
        or not target.read_bytes().startswith(scripts_header)
    ):
        try:
            scripts = load_scripts(cached_archive)
        except click.ClickException:
            cache_valid = False
        else:
            for name, data in scripts.items():
                _atomic_write(scripts_dir / name, data)
            if not target.read_bytes().startswith(scripts_header):
                _atomic_write(target, scripts_header + target.read_bytes())
                state["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            state["scripts"] = _script_hashes(scripts)
            _atomic_write(manifest, json.dumps(state, sort_keys=True).encode() + b"\n")
    if cache_valid and not refresh:
        if require_scripts:
            _require_scripts(target.read_bytes(), state["scripts"], ref)
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
        scripts = load_scripts(archive)
    except click.ClickException:
        if cache_valid:
            if require_scripts:
                _require_scripts(target.read_bytes(), state["scripts"], ref)
            target.touch()
            click.echo(
                f"Could not refresh asta-plugins@{ref}; using the cached copy", err=True
            )
            return
        raise
    if require_scripts:
        _require_scripts(asset, scripts, ref)
    archive_sha = hashlib.sha256(archive).hexdigest()
    archive_path = cache / "archives" / archive_sha
    scripts_dir = cache / "scripts" / archive_sha
    if scripts_dir.is_symlink():
        raise click.ClickException("Workspace scripts directory must not be a symlink")
    if archive_path.is_symlink():
        raise click.ClickException("Workspace source archive must not be a symlink")
    if (
        not archive_path.is_file()
        or hashlib.sha256(archive_path.read_bytes()).hexdigest() != archive_sha
    ):
        _atomic_write(archive_path, archive)
    managed = (
        f"override ASTA_WORKSPACE_SCRIPTS := .asta/cache/scripts/{archive_sha}\n"
        f"override ASTA_PLUGINS_REF := {ref}\n"
        f"override ASTA_WORKSPACE_ARCHIVE := .asta/cache/archives/{archive_sha}\n"
    ).encode() + asset
    # Keep old readers on their archive's scripts until the new rules are published.
    for name, data in scripts.items():
        _atomic_write(scripts_dir / name, data)
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
                "scripts": _script_hashes(scripts),
            },
            sort_keys=True,
        ).encode()
        + b"\n",
    )
    click.echo(f"Loaded workspace.mk from asta-plugins@{ref}")


PREVIEW_PORT = 4848
MAKE_PROBE_TIMEOUT = 10


def preview_url(env: Mapping[str, str]) -> str:
    codespace = env.get("CODESPACE_NAME")
    if codespace:
        domain = env.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN") or "app.github.dev"
        return f"https://{codespace}-{PREVIEW_PORT}.{domain}/"
    return f"http://localhost:{PREVIEW_PORT}/"


def preview_running() -> bool:
    import socket

    for host in ("127.0.0.1", "::1"):
        try:
            socket.create_connection((host, PREVIEW_PORT), 2).close()
        except OSError:
            continue
        return True
    return False


def make_has_preview(project: Path) -> bool:
    # Question mode skips the preview recipe, but can remake included rules or
    # evaluate shell expressions. Bound the probe; real Make handles a timeout.
    try:
        result = subprocess.run(
            ["make", "--question", "preview"],
            cwd=project,
            capture_output=True,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
            timeout=MAKE_PROBE_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        return True
    # Other Make errors must reach `make preview`, not be hidden by a fallback.
    return not (
        result.returncode == 2
        and re.search(r"No rule to make target [`']preview'\.", result.stderr)
    )


@workspace.command()
@click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
def preview(project: Path) -> None:
    """Start the project's live preview on port 4848.

    Delegates to `make preview` when available, otherwise uses Quarto directly.
    """
    project = project.resolve()
    makefile = (project / "Makefile").is_file()
    quarto = (project / "_quarto.yml").is_file()
    if not makefile and not quarto:
        click.echo("No Makefile or _quarto.yml found; nothing to preview")
        return
    if preview_running():
        raise click.ClickException(
            f"Port {PREVIEW_PORT} is already in use; cannot verify that the server "
            "belongs to this project. Use the existing server if appropriate, "
            "or stop it before starting this preview."
        )
    command = ["make", "preview"]
    try:
        if not makefile or (quarto and not make_has_preview(project)):
            command = ["quarto", "preview", "--no-browser", "--port", str(PREVIEW_PORT)]
        click.echo(f"Quarto preview: {preview_url(os.environ)}")
        result = subprocess.run(command, cwd=project, check=False)
    except KeyboardInterrupt:
        return
    except FileNotFoundError as exc:
        raise click.ClickException(f"{command[0]} is not installed") from exc
    if result.returncode not in (0, -signal.SIGINT, 130):
        raise click.ClickException(
            f"{' '.join(command)} failed (exit {result.returncode}); see the errors above."
        )
