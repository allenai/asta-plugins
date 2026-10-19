"""Fetch workspace build rules from the version selected by a project."""

import functools
import hashlib
import http.client
import http.server
import io
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import click

from asta.commands import workspace_versions
from asta.commands.overleaf import overleaf

WORKFLOW = "/.github/workflows/workspace-quarto-site.yml@"
ASSET = "plugins/asta-tools/skills/workspace/assets/workspace.mk"
ASSET_DIR = "plugins/asta-tools/skills/workspace/assets/"
# Scripts workspace.mk runs; a committed scripts/<name> takes precedence.
CHECK_SCRIPTS = ("quarto-check.sh", "wait-for-preview.sh")
VIEWER_SCRIPTS = ("paper-discovery.py", "paper-viewer.py")
# Cached when the selected ref ships it; `asta workspace what-changed` runs it.
DIFF_SCRIPT = "what-changed.py"
SCRIPTS = CHECK_SCRIPTS + VIEWER_SCRIPTS + (DIFF_SCRIPT,)
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


WORKFLOW_FILE = ".github/workflows/docs.yml"


def selected_source(project: Path) -> tuple[str, str]:
    workflow = project / WORKFLOW_FILE
    try:
        lines = workflow.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise click.ClickException(f"Missing {workflow}") from exc
    except UnicodeDecodeError as exc:
        raise click.ClickException(f"Workflow must be UTF-8: {workflow}") from exc
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


def _require_cli(rules: bytes, ref: str, cli: str | None) -> None:
    if message := workspace_versions.cli_too_old(rules, ref, cli, WORKFLOW_FILE):
        raise click.ClickException(message)


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


workspace.add_command(overleaf)


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
    archive = sync_workspace(project, refresh, require_scripts)
    if archive is not None and archive_has_asta_theme(archive):
        adopt_asta_theme(project)
        config = project.resolve() / "_quarto.yml"
        ignore = project.resolve() / ".gitignore"
        extension = project.resolve() / "_extensions/asta-theme"
        if (
            config.is_file()
            and not config.is_symlink()
            and ASTA_CSS in config.read_text(encoding="utf-8")
            and not ignore.is_symlink()
            and not extension.is_symlink()
        ):
            tracked = subprocess.run(
                ["git", "-C", str(project), "ls-files", "--", "_extensions/asta-theme"],
                capture_output=True,
                text=True,
                check=False,
            )
            # A committed directory is intentionally customized, not a cache.
            if tracked.returncode == 0 and not tracked.stdout.strip():
                previous = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
                if (
                    "_extensions/asta-theme" not in previous.splitlines()
                    and "_extensions/asta-theme/" not in previous.splitlines()
                ):
                    _atomic_write(
                        ignore,
                        (previous.rstrip("\n") + "\n_extensions/asta-theme/\n").encode(
                            "utf-8"
                        ),
                    )


SCAFFOLD_THEME = "    theme: cosmo\n"
ASTA_THEME = """    theme:
      dark: [cosmo, _extensions/asta-theme/dark.scss]
      light: [cosmo, _extensions/asta-theme/light.scss]
    # Asta's look: start dark, with a persistent toggle to light.
    # Set your own theme here to replace it.
    respect-user-color-scheme: false
"""
ASTA_CSS = "_extensions/asta-theme/asta.css"
ASTA_HEADER = "_extensions/asta-theme/asta-head.html"


def archive_has_asta_theme(archive: bytes) -> bool:
    """Only adopt a theme that the project's selected source can supply."""
    required = {
        ASSET_DIR + "_extensions/asta-theme/" + name
        for name in ("light.scss", "dark.scss", "asta.css", "asta-head.html")
    }
    found = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            for member in bundle:
                parts = member.name.split("/", 1)
                if len(parts) != 2 or parts[1] not in required:
                    continue
                if (
                    parts[1] in found
                    or not member.isfile()
                    or not 0 < member.size <= MAX_ASSET_BYTES
                ):
                    return False
                found.add(parts[1])
    except (tarfile.TarError, OSError):
        return False
    return found == required


def adopt_asta_theme(project: Path) -> bool:
    """Move a site still on the scaffold's default theme to Asta's look.

    Any other theme is the project's own choice and is left alone.
    """
    config = project.resolve() / "_quarto.yml"
    if config.is_symlink() or not config.is_file():
        return False
    text = config.read_text()
    # Deliberately recognize only the scaffold's block mappings. Leave flow
    # mappings, anchors and nonstandard indentation to the project owner. Scope
    # both theme and css edits to format.html, preserving all other formats.
    formats = list(re.finditer(r"^format:[ \t]*(?:#.*)?\n", text, re.MULTILINE))
    if len(formats) != 1:
        return False
    start = formats[0].end()
    end_match = re.search(r"^[^\s#]", text[start:], re.MULTILINE)
    end = start + end_match.start() if end_match else len(text)
    htmls = list(
        re.finditer(r"^  html:[ \t]*(?:#.*)?\n", text[start:end], re.MULTILINE)
    )
    if len(htmls) != 1:
        return False
    start += htmls[0].end()
    end_match = re.search(r"^ {0,2}[^\s#]", text[start:end], re.MULTILINE)
    end = start + end_match.start() if end_match else end
    html = text[start:end]
    if (
        "asta-theme" in html
        or re.search(r"^" + re.escape(SCAFFOLD_THEME), html, re.MULTILINE) is None
        or len(re.findall(r"^    theme:", html, re.MULTILINE)) != 1
    ):
        return False
    if re.search(r"^    respect-user-color-scheme:", html, re.MULTILINE):
        # An explicit project preference wins over the managed default.
        theme = ASTA_THEME.replace("    respect-user-color-scheme: false\n", "")
    else:
        theme = ASTA_THEME
    html = re.sub(
        r"^" + re.escape(SCAFFOLD_THEME),
        lambda _: theme,
        html,
        count=1,
        flags=re.MULTILINE,
    )
    # Add managed resources to the existing HTML lists without duplicate keys.
    for key, resource in (("css", ASTA_CSS), ("include-in-header", ASTA_HEADER)):
        if len(re.findall(rf"^    {key}:", html, re.MULTILINE)) > 1:
            return False
        entry = re.search(
            rf"^    {key}:([^\n]*)(?:\n|$)((?:      - .*\n)*)", html, re.MULTILINE
        )
        if entry is None:
            html = html.replace(theme, f"{theme}    {key}: {resource}\n")
        else:
            value = entry[1].strip()
            if value.startswith("[") and value.endswith("]"):
                own = value[1:-1].strip()
                joined = f"    {key}: [{resource}{', ' + own if own else ''}]\n"
            elif value and (value[0] in "|>&*!{[" or value.startswith("#")):
                return False
            else:
                if not value and re.match(r"    - ", html[entry.end() :]):
                    return False
                if not value and not entry[2]:
                    following = next(
                        (
                            line
                            for line in html[entry.end() :].splitlines()
                            if line.strip() and not line.lstrip().startswith("#")
                        ),
                        "",
                    )
                    if following.startswith("     ") and not following.startswith(
                        "      - "
                    ):
                        return False
                if value in ("null", "~"):
                    value = ""
                own = f"      - {value}\n" if value else entry[2]
                joined = f"    {key}:\n      - {resource}\n{own}"
            html = html[: entry.start()] + joined + html[entry.end() :]
    text = text[:start] + html + text[end:]
    _atomic_write(config, text.encode())
    click.echo(
        "Gave the site Asta's look in _quarto.yml; to customize or opt out, "
        "see the workspace developer guide, Site appearance (theme, css, and include-in-header)"
    )
    return True


def sync_workspace(project: Path, refresh: bool, require_scripts: bool) -> bytes | None:
    project = project.resolve()
    if (project / "workspace.mk").exists():
        if require_scripts:
            raise click.ClickException(
                "Local workspace.mk overrides managed rules; keep its project scripts"
            )
        click.echo("workspace.mk exists in the project; keeping its local override")
        return
    repository, ref = selected_source(project)
    if message := workspace_versions.pin_too_old(ref, WORKFLOW_FILE):
        raise click.ClickException(message)
    cli = workspace_versions.installed()
    if message := workspace_versions.pin_behind(ref, cli, WORKFLOW_FILE):
        click.echo(message, err=True)
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
        _require_cli(target.read_bytes(), ref, cli)
        if require_scripts:
            _require_scripts(target.read_bytes(), state["scripts"], ref)
        target.touch()
        if not re.fullmatch(r"[0-9a-fA-F]{40}", ref):
            click.echo(
                f"Using cached {ref}; run 'asta workspace sync --refresh' to update",
                err=True,
            )
        click.echo(f"workspace.mk already cached from asta-plugins@{ref}")
        return cached_archive
    try:
        asset, archive = load_asset(repository, source_ref)
        scripts = load_scripts(archive)
    except click.ClickException:
        if cache_valid:
            _require_cli(target.read_bytes(), ref, cli)
            if require_scripts:
                _require_scripts(target.read_bytes(), state["scripts"], ref)
            target.touch()
            click.echo(
                f"Could not refresh asta-plugins@{ref}; using the cached copy", err=True
            )
            return cached_archive
        raise
    _require_cli(asset, ref, cli)
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
    return archive


@workspace.command("bump-pin")
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
)
def bump_pin(project: Path) -> None:
    """Commit an upgrade from an older release pin to the installed asta release."""
    project = project.resolve()
    workflow = project / WORKFLOW_FILE
    for relative in (".github", ".github/workflows", WORKFLOW_FILE):
        if (project / relative).is_symlink():
            raise click.ClickException(
                f"Workspace workflow path must not contain symlinks: {relative}"
            )
    _, ref = selected_source(project)
    target = workspace_versions.pin_target(ref, workspace_versions.installed())
    if target is None:
        click.echo(f"Pin asta-plugins@{ref} is current; nothing to do")
        return
    status = _git(project, "status", "--porcelain", "--", WORKFLOW_FILE)
    if status.returncode != 0:
        raise click.ClickException(
            f"Could not check the workflow's Git status: {status.stderr.strip()}"
        )
    if status.stdout.strip():
        raise click.ClickException(
            f"{WORKFLOW_FILE} has uncommitted changes; commit them first"
        )
    original = workflow.read_bytes()
    lines = original.decode("utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if match := WORKFLOW_LINE.fullmatch(line.rstrip("\r\n")):
            start, end = match.span("ref")
            lines[index] = line[:start] + target + line[end:]
    message = f"Move workspace pin to asta-plugins@{target}"
    head = _git(project, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise click.ClickException("Could not determine the workflow's Git HEAD")
    commit_started = False
    try:
        workflow.write_bytes("".join(lines).encode("utf-8"))
        if selected_source(project)[1] != target:
            raise click.ClickException(f"Could not move the pin in {workflow}")
        commit_started = True
        committed = _git(project, "commit", "-m", message, "--", WORKFLOW_FILE)
        if committed.returncode != 0:
            raise click.ClickException(
                f"Could not commit the pin move: {committed.stderr.strip()}"
            )
        current = _git(project, "rev-parse", "HEAD")
        if current.returncode != 0:
            raise click.ClickException("Could not read the pin move's commit SHA")
        sha = current.stdout.strip()
    except BaseException:
        # A signal can arrive after Git committed but before subprocess.run returned.
        # Never restore the old bytes over an already-advanced HEAD.
        if commit_started:
            try:
                current = _git(project, "rev-parse", "HEAD")
            except OSError:
                current = None
            if current is None or current.returncode != 0:
                click.echo(
                    f"Could not determine whether the pin move committed; "
                    f"{WORKFLOW_FILE} may still be modified. Inspect Git HEAD and "
                    "the workflow before opening the PR; no rollback was attempted.",
                    err=True,
                )
                raise
            if current.stdout != head.stdout:
                click.echo(f"Committed {current.stdout.strip()}: {message}", err=True)
                raise
        workflow.write_bytes(original)
        raise
    click.echo(f"Committed {sha}: {message} (was @{ref})")


def _git(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(project), *args], capture_output=True, text=True, check=False
    )


def diff_script(project: Path) -> Path:
    """Locate what-changed.py the way the PR preview does: project copy first."""
    local = project / "scripts" / DIFF_SCRIPT
    if local.is_file():
        return local
    guidance = (
        f"No {DIFF_SCRIPT} for this project: select a newer asta-plugins ref in "
        f"docs.yml and run 'asta workspace sync --refresh', or add scripts/{DIFF_SCRIPT}"
    )
    try:
        with redirect_stdout(sys.stderr):
            sync_workspace(project, refresh=False, require_scripts=False)
    except click.ClickException as exc:
        raise click.ClickException(f"{exc.format_message()}. {guidance}") from exc
    try:
        state = json.loads((project / ".asta/cache/workspace.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    archive_sha = state.get("archive_sha256") if isinstance(state, dict) else None
    scripts = state.get("scripts") if isinstance(state, dict) else None
    if (
        isinstance(archive_sha, str)
        and re.fullmatch(r"[0-9a-f]{64}", archive_sha)
        and isinstance(scripts, dict)
        and DIFF_SCRIPT in scripts
    ):
        cached = project / ".asta/cache/scripts" / archive_sha / DIFF_SCRIPT
        if (
            cached.is_file()
            and not cached.is_symlink()
            and not cached.parent.is_symlink()
        ):
            return cached
    raise click.ClickException(guidance)


def render_site(directory: Path, label: str) -> Path:
    if not directory.is_dir():
        raise click.ClickException(
            f"Project directory does not exist for {label}: {directory}"
        )
    click.echo(f"Rendering {label} with 'make render'", err=True)
    with preview_process(
        ["make", "render"],
        directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ) as process:
        for line in process.stdout:
            click.echo(line, nl=False, err=True)
        process.wait()
    if process.returncode != 0:
        raise click.ClickException(f"'make render' failed for {label}")
    site = directory / "_site"
    if not site.is_dir():
        raise click.ClickException(f"'make render' did not produce _site for {label}")
    return site


COMPARISON_DIR = Path(".asta/cache/what-changed")


def _ls_files(repository: Path, *args: str) -> list[str]:
    listed = _git(repository, "ls-files", "-z", *args)
    if listed.returncode != 0:
        raise click.ClickException(
            f"Could not list the working tree: {listed.stderr.strip()}"
        )
    return [name for name in listed.stdout.split("\0") if name]


def _is_env_file(name: str) -> bool:
    base = Path(name).name
    return base == ".env" or base.startswith(".env.")


def working_copy(repository: Path, prefix: str, destination: Path) -> Path:
    """Copy render inputs only: Git-visible files plus the synced workspace cache.

    Other ignored files (virtualenvs, outputs, caches) and untracked .env files
    stay out, so comparisons stay quick and do not duplicate secrets. The copy is
    a linked worktree, like the baseline, so `git rev-parse --git-common-dir`
    finds the main checkout (and its ignored .venv) from both renders.
    """
    project = repository / prefix
    added = _git(
        repository,
        "worktree",
        "add",
        "--detach",
        "--no-checkout",
        str(destination),
        "HEAD",
    )
    if added.returncode != 0:
        raise click.ClickException(
            f"Could not copy the working tree: {added.stderr.strip()}"
        )
    entries = _git(repository, "ls-files", "--stage", "-z")
    if entries.returncode != 0:
        raise click.ClickException(
            f"Could not read the working-tree index: {entries.stderr.strip()}"
        )
    # Rebuild a standalone index, including staging in linked/split-index worktrees.
    indexed = subprocess.run(
        ["git", "-C", str(destination), "update-index", "-z", "--index-info"],
        input=entries.stdout,
        capture_output=True,
        text=True,
        check=False,
    )
    if indexed.returncode != 0:
        raise click.ClickException(
            f"Could not index the working tree: {indexed.stderr.strip()}"
        )
    untracked = [
        name
        for name in _ls_files(repository, "--others", "--exclude-standard")
        if not _is_env_file(name)
    ]
    live = (project / "_site", project / ".quarto")
    files = dict.fromkeys(_ls_files(repository, "--cached") + untracked)
    click.echo(f"Copying {len(files)} Git-visible render inputs", err=True)
    for name in files:
        source = repository / name
        if not os.path.lexists(source) or any(
            source == path or path in source.parents for path in live
        ):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir() and not source.is_symlink():
            # A submodule or nested repository checkout.
            shutil.copytree(
                source,
                target,
                symlinks=True,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git"),
            )
        else:
            shutil.copy2(source, target, follow_symlinks=False)

    # The Makefile includes rules synced here; reuse them instead of re-syncing.
    cache = project / ".asta/cache"

    def ignore(directory, names):
        if Path(directory) != cache:
            return set()
        return {
            name
            for name in names
            if name == "what-changed" or name.startswith(".what-changed-")
        }

    if cache.is_dir() and not cache.is_symlink():
        shutil.copytree(
            cache,
            destination / prefix / ".asta/cache",
            symlinks=True,
            dirs_exist_ok=True,
            ignore=ignore,
        )
    return destination / prefix


@contextmanager
def _comparison_directory():
    temporary = Path(tempfile.mkdtemp(prefix="asta-what-changed-"))
    try:
        yield temporary
    finally:
        try:
            with preview_cleanup():
                # Git owns both worktrees; keep failed removals recoverable.
                if not any(
                    (temporary / name).exists() for name in ("baseline", "working")
                ):
                    temporary.rmdir()
        except OSError as exc:
            click.echo(f"Warning: comparison directory cleanup failed: {exc}", err=True)


def _publish(staged: Path, owned: Path) -> None:
    """Replace the command-owned comparison directory with a finished one."""
    previous = staged.with_name(staged.name + ".previous")
    try:
        if owned.exists() or owned.is_symlink():
            owned.replace(previous)
        staged.replace(owned)
    except BaseException:
        with preview_cleanup():
            if previous.exists() or previous.is_symlink():
                previous.replace(owned)
        raise
    try:
        if previous.is_symlink() or previous.is_file():
            previous.unlink()
        elif previous.exists():
            shutil.rmtree(previous)
    except OSError as exc:
        click.echo(f"Warning: previous comparison cleanup failed: {exc}", err=True)


@workspace.command("what-changed")
@click.argument("ref")
@click.option(
    "--project",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("."),
)
def what_changed(ref: str, project: Path) -> None:
    """Show what changed in the rendered site since a git REF (tag, branch, commit).

    Renders REF and a private working-tree copy with the project's own 'make render' and
    compares them with the what-changed.py the PR preview uses. The page is
    written to a copy of the rendered site under .asta/cache/what-changed/,
    which this command owns and replaces on each run. Live _site/ is untouched.
    Requires Git 2.30 or newer. Choose a trusted REF: its
    build code runs locally. The baseline contains only committed files.
    """
    try:
        with preview_signals():
            compare_workspace(ref, project)
    except KeyboardInterrupt:
        raise click.exceptions.Exit(130) from None
    except PreviewTerminated as exc:
        raise click.exceptions.Exit(128 + exc.signum) from None


def compare_workspace(ref: str, project: Path) -> None:
    project = project.resolve()
    if (project / ".asta").is_symlink() or (project / ".asta/cache").is_symlink():
        raise click.ClickException("Workspace cache must not be a symlink")
    try:
        repository = _git(project, "rev-parse", "--show-toplevel")
    except FileNotFoundError as exc:
        raise click.ClickException("git is required to compare the workspace") from exc
    if repository.returncode != 0:
        raise click.ClickException(f"Not a git repository: {project}")
    version = _git(project, "--version")
    parsed = re.search(r"\bgit version (\d+)\.(\d+)", version.stdout)
    if version.returncode != 0 or not parsed:
        raise click.ClickException(
            "Cannot determine Git version; Git 2.30 or newer is required"
        )
    if tuple(map(int, parsed.groups())) < (2, 30):
        raise click.ClickException(
            f"Git 2.30 or newer is required; found {version.stdout.strip()}"
        )
    commit = _git(
        project,
        "rev-parse",
        "--verify",
        "--quiet",
        "--end-of-options",
        f"{ref}^{{commit}}",
    )
    if commit.returncode != 0 or not commit.stdout.strip():
        raise click.ClickException(f"Unknown git ref: {ref}")
    prefix = _git(project, "rev-parse", "--show-prefix")
    if prefix.returncode != 0:
        raise click.ClickException(
            "Could not locate the project within its git repository"
        )
    owned = project / COMPARISON_DIR
    with _comparison_directory() as tmp:
        baseline = tmp / "baseline"
        added = None
        try:
            added = _git(
                project,
                "worktree",
                "add",
                "--detach",
                str(baseline),
                commit.stdout.strip(),
            )
            if added.returncode != 0:
                raise click.ClickException(
                    f"Could not check out {ref}: {added.stderr.strip()}"
                )
            baseline_project = baseline / prefix.stdout.rstrip("\n")
            if not baseline_project.is_dir():
                raise click.ClickException(
                    f"Project directory does not exist for {ref}: {baseline_project}"
                )
            script = diff_script(project)
            old_site = render_site(baseline_project, ref)
            copied_project = working_copy(
                Path(repository.stdout.rstrip("\n")),
                prefix.stdout.rstrip("\n"),
                tmp / "working",
            )
            new_site = render_site(copied_project, "the working tree")
            # The page sits at the root of a site copy so its relative links
            # to changed pages resolve, as in the PR preview.
            if (project / ".asta").is_symlink() or owned.parent.is_symlink():
                raise click.ClickException("Workspace cache must not be a symlink")
            owned.parent.mkdir(parents=True, exist_ok=True)
            staged = Path(tempfile.mkdtemp(prefix=".what-changed-", dir=owned.parent))
            try:
                # Copy entries, not the root's metadata: staging stays 0700.
                for entry in new_site.iterdir():
                    if entry.is_dir() and not entry.is_symlink():
                        shutil.copytree(entry, staged / entry.name, symlinks=True)
                    else:
                        shutil.copy2(entry, staged / entry.name, follow_symlinks=False)
                report = staged / "what-changed.html"
                report.unlink(missing_ok=True)
                with preview_process(
                    [
                        sys.executable,
                        str(script),
                        "--old",
                        str(old_site),
                        "--new",
                        str(new_site),
                        "--out",
                        str(report),
                        "--title",
                        f"Changes since {ref}",
                    ],
                    project,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                ) as process:
                    for line in process.stdout:
                        click.echo(line, nl=False, err=True)
                    returncode = process.wait()
                if returncode != 0:
                    raise click.ClickException(
                        f"{DIFF_SCRIPT} failed (exit {returncode}): {script}"
                    )
                if (
                    report.is_symlink()
                    or not report.is_file()
                    or report.stat().st_size == 0
                ):
                    raise click.ClickException(
                        f"{DIFF_SCRIPT} did not write nonempty HTML"
                    )
                try:
                    _publish(staged, owned)
                except OSError as exc:
                    raise click.ClickException(
                        f"Could not publish the comparison: {exc}"
                    ) from exc
            finally:
                with preview_cleanup():
                    shutil.rmtree(staged, ignore_errors=True)
        finally:
            with preview_cleanup():
                if (tmp / "working").exists():
                    working = tmp / "working"
                    removed = _git(
                        project, "worktree", "remove", "--force", str(working)
                    )
                    if removed.returncode != 0:
                        click.echo(
                            f"Warning: working worktree cleanup failed for {working}: {removed.stderr.strip()}. "
                            f"Resolve the cause, then run 'git worktree remove --force {shlex.quote(str(working))}'.",
                            err=True,
                        )
                removed = _git(project, "worktree", "remove", "--force", str(baseline))
                if removed.returncode != 0 and (
                    added is None or added.returncode == 0 or baseline.exists()
                ):
                    click.echo(
                        f"Warning: baseline worktree cleanup failed for {baseline}: {removed.stderr.strip()}. "
                        f"Resolve the cause, then run 'git worktree remove --force {shlex.quote(str(baseline))}'.",
                        err=True,
                    )
    page = owned / "what-changed.html"
    click.echo(f"Wrote {page}")
    url = preview_url(os.environ, WHAT_CHANGED_PORT) + page.name
    click.echo(f"View it with `asta workspace preview --what-changed`, at {url}")


PREVIEW_PORT = 4848
# A separate port, so the comparison can be viewed while the live preview runs.
WHAT_CHANGED_PORT = 4849
PREVIEW_STATE = Path(".asta/cache/preview.json")


def preview_url(env: Mapping[str, str], port: int = PREVIEW_PORT) -> str:
    codespace = env.get("CODESPACE_NAME")
    if codespace:
        domain = env.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN") or "app.github.dev"
        return f"https://{codespace}-{port}.{domain}/"
    return f"http://localhost:{port}/"


def comparison_server(directory: Path, port: int) -> http.server.ThreadingHTTPServer:
    """Serve the what-changed site copy; requests resolve its path afresh, so a
    rerun of what-changed is picked up without restarting."""
    root = directory.parent.resolve() / directory.name
    forwarded_host = None

    class SiteHandler(http.server.SimpleHTTPRequestHandler):
        def send_head(self):
            try:
                host = urlsplit("//" + self.headers.get("Host", "").lower())
                valid_host = (
                    host.hostname in ("localhost", "127.0.0.1", forwarded_host)
                    and bool(host.hostname)
                    and host.username is None
                    and host.password is None
                    and not host.path
                    and not host.query
                    and not host.fragment
                    and (host.port is None or 0 < host.port <= 65535)
                    and (
                        host.hostname != forwarded_host or host.netloc == forwarded_host
                    )
                )
            except ValueError:
                valid_host = False
            if not valid_host:
                self.send_error(403, "Unrecognized preview host")
                return None
            try:
                path = Path(self.translate_path(self.path)).resolve()
                # Check each request: later comparisons can replace the site copy.
                # A swap between this check and the open is a known limit: a
                # process that can write this private cache already has the
                # user's access.
                paths = [path]
                if path.is_dir():
                    paths += [
                        (path / name).resolve() for name in ("index.html", "index.htm")
                    ]
                if any(not candidate.is_relative_to(root) for candidate in paths):
                    raise ValueError("Path leaves the comparison site")
            except (OSError, RuntimeError, ValueError):
                self.send_error(
                    403, "Path leaves the comparison site or is unavailable"
                )
                return None
            if path.exists() and not path.is_dir() and not path.is_file():
                self.send_error(404, "Not a site file")
                return None
            return super().send_head()

        def list_directory(self, path):
            self.send_error(404, "Directory listing is disabled")
            return None

    handler = functools.partial(SiteHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    if os.environ.get("CODESPACE_NAME"):
        forwarded_host = urlsplit(preview_url(os.environ, server.server_port)).hostname
    return server


def serve_what_changed(project: Path) -> None:
    owned = project.resolve() / COMPARISON_DIR
    if not (owned / "what-changed.html").is_file():
        raise click.ClickException(
            "No comparison page yet; run `asta workspace what-changed <ref>` first"
        )
    url = preview_url(os.environ, WHAT_CHANGED_PORT) + "what-changed.html"
    try:
        server = comparison_server(owned, WHAT_CHANGED_PORT)
    except OSError as exc:
        raise click.ClickException(
            f"Port {WHAT_CHANGED_PORT} is in use ({exc.strerror}). If an earlier "
            f"`asta workspace preview --what-changed` is running, it already "
            f"serves the latest page: {url}"
        ) from exc
    click.echo(f"Serving What changed at {url} (Ctrl-C to stop)")
    with server:
        server.serve_forever()


def preview_running() -> bool:
    for host in ("127.0.0.1", "::1"):
        try:
            socket.create_connection((host, PREVIEW_PORT), 2).close()
        except OSError:
            continue
        return True
    return False


def recorded_preview(project: Path) -> bool:
    # Windows does not provide POSIX's non-signaling kill(pid, 0) probe.
    if os.name != "posix":
        return False
    try:
        state = json.loads((project / PREVIEW_STATE).read_text())
        pid = state["pid"]
        if (
            state["project"] != str(project)
            or type(pid) is not int
            or pid <= 0
            or pid == os.getpid()
        ):
            return False
        os.kill(pid, 0)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return False
    return True


class PreviewTerminated(BaseException):
    def __init__(self, signum: int):
        self.signum = signum


@contextmanager
def preview_signals():
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    handlers = {}

    def terminate(signum, frame):
        raise PreviewTerminated(signum)

    try:
        for signum in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
            if signum is not None:
                handlers[signum] = signal.signal(signum, terminate)
        yield
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


@contextmanager
def preview_cleanup():
    """Let cleanup finish even if the terminal sends another stop signal."""
    handlers = {}
    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (
                signal.SIGINT,
                signal.SIGTERM,
                getattr(signal, "SIGHUP", None),
            ):
                if signum is not None:
                    handlers[signum] = signal.signal(signum, signal.SIG_IGN)
        yield
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def stop_preview(process: subprocess.Popen, signum: int) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signum)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (
        ProcessLookupError,
        subprocess.TimeoutExpired,
        KeyboardInterrupt,
        PreviewTerminated,
    ):
        pass
    finally:
        # Make can exit before its recipe children; stop the whole owned group.
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except (subprocess.TimeoutExpired, KeyboardInterrupt, PreviewTerminated):
            pass


@contextmanager
def preview_process(command: list[str], project: Path, **kwargs):
    process = None
    try:
        try:
            process = subprocess.Popen(
                command, cwd=project, start_new_session=os.name == "posix", **kwargs
            )
        except FileNotFoundError as exc:
            raise click.ClickException(f"{command[0]} is not installed") from exc
        yield process
    except BaseException as exc:
        if process is not None:
            signum = exc.signum if isinstance(exc, PreviewTerminated) else signal.SIGINT
            with preview_cleanup():
                stop_preview(process, signum)
        raise


def run_preview(command: list[str], project: Path) -> int:
    with preview_process(command, project) as process:
        return process.wait()


def run_make_preview(project: Path) -> tuple[int, bool]:
    """Stream Make errors and recognize its final missing-preview diagnostic."""
    env = {**os.environ, "LC_ALL": "C", "LANGUAGE": "C"}
    for name in ("MAKELEVEL", "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES"):
        env.pop(name, None)
    with preview_process(
        ["make", "preview"],
        project,
        env=env,
        stderr=subprocess.PIPE,
    ) as process:
        diagnostic = b""
        with process.stderr:
            for line in process.stderr:
                click.echo(line.decode(errors="replace"), err=True, nl=False)
                if line.strip():
                    diagnostic = line.strip()
        returncode = process.wait()
    no_rule = (
        re.fullmatch(
            rb"(?:.*[/\\])?g?make: \*\*\* No rule to make target [`']preview'\.\s+Stop\.",
            diagnostic,
        )
        is not None
    )
    return returncode, returncode == 2 and no_rule


@workspace.command()
@click.option(
    "--project",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("."),
)
@click.option(
    "--what-changed",
    "what_changed_page",
    is_flag=True,
    help="Serve the page from `asta workspace what-changed` on port 4849 instead.",
)
def preview(project: Path, what_changed_page: bool) -> None:
    """Ensure the project's live preview is running on port 4848.

    Safe to run repeatedly: if this project's preview is already running, prints
    its URL and exits. If that launcher is still starting, asks you to retry.
    Runs `make preview`, falling back to `quarto preview` if Make is unavailable
    or has no `preview` rule. With --what-changed, serves the latest
    `asta workspace what-changed` page instead, until stopped.
    """
    try:
        with preview_signals():
            if what_changed_page:
                serve_what_changed(project)
            else:
                preview_project(project)
    except KeyboardInterrupt:
        raise click.exceptions.Exit(130) from None
    except PreviewTerminated as exc:
        raise click.exceptions.Exit(128 + exc.signum) from None


def preview_project(project: Path) -> None:
    project = project.resolve()
    makefile = any(
        (project / name).is_file() for name in ("GNUmakefile", "makefile", "Makefile")
    )
    quarto = (project / "_quarto.yml").is_file()
    if not makefile and not quarto:
        click.echo("No Makefile or _quarto.yml found; nothing to preview")
        return
    url = preview_url(os.environ)
    state = project / PREVIEW_STATE
    if recorded_preview(project):
        if preview_running():
            click.echo(f"Preview already running: {url}")
            return
        raise click.ClickException(
            "This project's preview is still starting or not listening; "
            "check its terminal and retry."
        )
    if preview_running():
        raise click.ClickException(
            f"Port {PREVIEW_PORT} is in use by another process; stop it to start "
            "this project's preview."
        )
    owner = {"pid": os.getpid(), "project": str(project)}
    try:
        _atomic_write(state, json.dumps(owner).encode())
    except OSError as exc:
        raise click.ClickException(f"Cannot record preview startup: {exc}") from exc
    command = ["make", "preview"] if makefile else []
    try:
        if command and shutil.which("make") is None:
            if not quarto:
                raise click.ClickException("make is not installed")
            click.echo("make is not installed; using quarto preview")
            command = []
        click.echo(f"Preview URL (once serving): {url}")
        if command:
            returncode, no_rule = run_make_preview(project)
            if no_rule and quarto:
                click.echo(
                    "No `preview` rule in the Makefile; using quarto preview "
                    "(the Make diagnostic above is expected)"
                )
                command = []
        if not command:
            command = ["quarto", "preview", "--no-browser", "--port", str(PREVIEW_PORT)]
            if shutil.which("quarto") is None:
                raise click.ClickException("quarto is not installed")
            returncode = run_preview(command, project)
    finally:
        with preview_cleanup():
            try:
                if json.loads(state.read_text()) == owner:
                    state.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
    if returncode in (-signal.SIGINT, 130):
        raise click.exceptions.Exit(130)
    if returncode != 0:
        raise click.ClickException(
            f"{' '.join(command)} failed (exit {returncode}); see the errors above."
        )
