"""Fetch workspace build rules from the version selected by a project."""

import concurrent.futures
import functools
import hashlib
import http.client
import http.server
import io
import json
import os
import posixpath
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import click
import yaml

from asta.commands import workspace_versions
from asta.commands.overleaf import overleaf

WORKFLOW = "/.github/workflows/workspace-quarto-site.yml@"
WORKFLOW_SOURCE = re.compile(r"[A-Za-z0-9_.-]+/(?i:asta-plugins)" + re.escape(WORKFLOW))
ASSET = "plugins/asta-tools/skills/workspace/assets/workspace.mk"
ASSET_DIR = "plugins/asta-tools/skills/workspace/assets/"
# Scripts workspace.mk runs; a committed scripts/<name> takes precedence.
CHECK_SCRIPTS = ("quarto-check.sh", "wait-for-preview.sh")
VIEWER_SCRIPTS = ("paper-discovery.py", "paper-viewer.py")
# Cached when the selected ref ships it; `asta workspace what-changed` runs it.
DIFF_SCRIPT = "what-changed.py"
# Optional beside DIFF_SCRIPT: publishes marked live decks without browser dependencies.
DECK_SCRIPT = "deck-review.py"
SCRIPTS = CHECK_SCRIPTS + VIEWER_SCRIPTS + (DIFF_SCRIPT, DECK_SCRIPT)
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


def _workspace_job_lines(
    text: str, workflow: Path
) -> list[tuple[int, yaml.ScalarNode | None]]:
    """Locate workspace calls and their own site inputs without rewriting YAML."""

    def field(node, name):
        if not isinstance(node, yaml.MappingNode):
            return None
        matches = [
            (key, value)
            for key, value in node.value
            if isinstance(key, yaml.ScalarNode) and key.value == name
        ]
        if len(matches) > 1:
            raise click.ClickException(f"Duplicate {name} key in {workflow}")
        return matches[0] if matches else None

    try:
        document = yaml.compose(text, Loader=yaml.BaseLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise click.ClickException(f"Invalid YAML in {workflow}") from exc
    jobs = field(document, "jobs")
    if jobs is None or not isinstance(jobs[1], yaml.MappingNode):
        return []
    result = []
    job_names = set()
    for name, job in jobs[1].value:
        if not isinstance(name, yaml.ScalarNode):
            continue
        if name.value in job_names:
            raise click.ClickException(f"Duplicate job key in {workflow}")
        job_names.add(name.value)
        uses = field(job, "uses")
        inputs = field(job, "with")
        site_dir = field(inputs[1], "site-dir") if inputs else None
        if (
            uses
            and isinstance(uses[1], yaml.ScalarNode)
            and WORKFLOW_SOURCE.match(uses[1].value.strip())
        ):
            result.append(
                (
                    uses[0].start_mark.line,
                    site_dir[1]
                    if site_dir and isinstance(site_dir[1], yaml.ScalarNode)
                    else None,
                )
            )
    return result


def _workflow_source_lines(text: str, workflow: Path) -> list[tuple[int, re.Match]]:
    lines = text.splitlines()
    sources = []
    # A YAML job alias can refer to the same source line more than once.
    for index in sorted({index for index, _ in _workspace_job_lines(text, workflow)}):
        match = WORKFLOW_LINE.fullmatch(lines[index])
        if match is None:
            raise click.ClickException(
                f"Invalid asta-plugins workflow line in {workflow}; "
                "write the workspace uses: and its literal source on one line"
            )
        sources.append((index, match))
    return sources


def _unrelated_workflow_prefix(text: str, workflow: Path, site: str) -> bool:
    """Prove an EOF-truncated root unrelated using only parsed YAML events.

    Closing open collections lets the normal job parser inspect the prefix,
    including aliases and block scalars. Never use this synthetic document to
    select a source or edit a pin. If parsing stopped before EOF, later content
    could still select this site, so the original validation error must stand.
    """
    events = []
    endings = []
    try:
        for event in yaml.parse(text, Loader=yaml.BaseLoader):
            events.append(event)
            if isinstance(event, yaml.DocumentStartEvent):
                endings.append(yaml.DocumentEndEvent())
            elif isinstance(event, yaml.MappingStartEvent):
                endings.append(yaml.MappingEndEvent())
            elif isinstance(event, yaml.SequenceStartEvent):
                endings.append(yaml.SequenceEndEvent())
            elif isinstance(
                event,
                (yaml.DocumentEndEvent, yaml.MappingEndEvent, yaml.SequenceEndEvent),
            ):
                endings.pop()
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        if mark is None or mark.index != len(text):
            return False
        try:
            prefix = yaml.emit([*events, *reversed(endings), yaml.StreamEndEvent()])
            jobs = _workspace_job_lines(prefix, workflow)
        except (yaml.YAMLError, click.ClickException):
            return False
        return not any(
            directory is not None and posixpath.normpath(directory.value) == site
            for _, directory in jobs
        )
    # Parsing succeeded: the validation error concerned structure (for example
    # duplicate keys or an undefined alias), which a prefix cannot disambiguate.
    return False


def workflow_root(project: Path) -> Path:
    """Return the directory whose docs.yml publishes project.

    GitHub runs only the repository root's workflows, so a site in a subfolder
    uses the root docs.yml whose site-dir names it.
    """
    project = project.resolve()
    # A submodule is its own repository, just like a worktree with a .git file.
    root = next(
        (
            parent
            for parent in (project, *project.parents)
            if (parent / ".git").exists()
        ),
        project,
    )
    if root == project:
        return project
    workflow = root / WORKFLOW_FILE
    try:
        _reject_workflow_symlinks(workflow)
    except click.ClickException:
        local = project / WORKFLOW_FILE
        _reject_workflow_symlinks(local)
        if local.is_file():
            return project
        raise
    try:
        text = workflow.read_text(encoding="utf-8")
    except FileNotFoundError:
        return project
    except UnicodeDecodeError as exc:
        raise click.ClickException(f"Workflow must be UTF-8: {workflow}") from exc
    except OSError as exc:
        raise click.ClickException(f"Could not read {workflow}: {exc}") from exc
    site = project.relative_to(root).as_posix()
    try:
        job_lines = _workspace_job_lines(text, workflow)
    except click.ClickException:
        if _unrelated_workflow_prefix(text, workflow, site):
            return project
        raise
    if any(
        directory is not None and posixpath.normpath(directory.value) == site
        for _, directory in job_lines
    ):
        if len(job_lines) != 1:
            raise click.ClickException(
                f"Ambiguous workspace workflow: {workflow}; "
                "a subfolder site requires exactly one workspace job, "
                "with its own site-dir input"
            )
        return root
    return project


def workflow_file(project: Path) -> Path:
    return workflow_root(project) / WORKFLOW_FILE


def selected_source(project: Path) -> tuple[str, str]:
    return _source_from_workflow(workflow_file(project))


def _source_from_workflow(
    workflow: Path, *, original: bytes | None = None
) -> tuple[str, str]:
    _reject_workflow_symlinks(workflow)
    try:
        text = (workflow.read_bytes() if original is None else original).decode("utf-8")
    except FileNotFoundError as exc:
        raise click.ClickException(
            f"Missing {workflow}; for a subfolder site, keep docs.yml at the "
            "repository root in .github/workflows and set its workspace job's "
            "with.site-dir to the site's relative path"
        ) from exc
    except UnicodeDecodeError as exc:
        raise click.ClickException(f"Workflow must be UTF-8: {workflow}") from exc
    refs = [
        (match.group("repository"), match.group("ref"))
        for _, match in _workflow_source_lines(text, workflow)
    ]
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
@click.option(
    "--check-selection",
    is_flag=True,
    help="Validate the selected workflow offline, without fetching rules or moving pins.",
)
def sync(
    project: Path, refresh: bool, require_scripts: bool, check_selection: bool = False
) -> None:
    """Load shared Makefile rules at the version selected in docs.yml."""
    if check_selection:
        if refresh or require_scripts:
            raise click.UsageError(
                "--check-selection cannot be combined with --refresh or --require-scripts"
            )
        selected_source(project)
        return
    archive = sync_workspace(project, refresh, require_scripts)
    if archive is not None and archive_has_asta_theme(archive):
        makefile = project.resolve() / "Makefile"
        if not makefile.is_file() or not re.search(
            r"^include[ \t]+\.asta/cache/workspace\.mk[ \t]*(?:#.*)?$",
            makefile.read_text(encoding="utf-8"),
            re.MULTILINE,
        ):
            click.echo(
                "Warning: theme adoption skipped: Makefile must use "
                "'include .asta/cache/workspace.mk' to fetch managed theme assets. "
                "Keep your current theme or migrate to the managed Makefile first.",
                err=True,
            )
            return
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
                        (
                            previous.rstrip("\n")
                            + ("\n" if previous else "")
                            + "_extensions/asta-theme/\n"
                        ).encode("utf-8"),
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
ASTA_THEME_FILES = (
    "light.scss",
    "dark.scss",
    "asta.css",
    "asta-head.html",
    "fonts/Manrope.woff2",
    "fonts/RobotoMono.woff2",
    "fonts/Manrope-OFL.txt",
    "fonts/RobotoMono-OFL.txt",
)


def archive_has_asta_theme(archive: bytes) -> bool:
    """Only adopt a theme that the project's selected source can supply."""
    required = {
        ASSET_DIR + "_extensions/asta-theme/" + name for name in ASTA_THEME_FILES
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
    text = config.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"  # so a final block-list item is matched
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
        theme = ASTA_THEME.replace(
            "    respect-user-color-scheme: false\n", ""
        ).replace(
            "    # Asta's look: start dark, with a persistent toggle to light.\n", ""
        )
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
    project_css = ""
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
            if key == "css":
                project_css = (
                    own
                    if value.startswith("[")
                    else ", ".join(re.findall(r"^\s*-\s*(.+)$", own, re.MULTILINE))
                )
            html = html[: entry.start()] + joined + html[entry.end() :]
    text = text[:start] + html + text[end:]
    _atomic_write(config, text.encode("utf-8"))
    click.echo(
        "Gave the site Asta's look in _quarto.yml; to customize or opt out, "
        "see the workspace developer guide, Site appearance (theme, css, and include-in-header)"
    )
    if project_css:
        click.echo(
            "Warning: existing project CSS is kept after Asta's stylesheet. "
            f"Review its colors in dark and light mode: {project_css}",
            err=True,
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
    workflow = workflow_file(project)
    _reject_workflow_symlinks(workflow)
    try:
        original = workflow.read_bytes()
    except FileNotFoundError as exc:
        raise click.ClickException(
            f"Missing {workflow}; for a subfolder site, keep docs.yml at the "
            "repository root in .github/workflows and set its workspace job's "
            "with.site-dir to the site's relative path"
        ) from exc
    repository, ref = _source_from_workflow(workflow, original=original)
    original_ref = ref
    if not _is_unattended():
        ref = workspace_versions.pin_target(ref, workspace_versions.installed()) or ref

    def validate_workflow() -> None:
        try:
            _reject_workflow_symlinks(workflow)
            if workflow.read_bytes() == original and workflow_file(project) == workflow:
                return
        except (OSError, click.ClickException) as exc:
            cause = f": {exc}"
        else:
            cause = ""
        # Make can otherwise run newer cached rules after this failed sync.
        cache = project / ".asta/cache"
        for name in ("workspace.mk", "workspace.json"):
            (cache / name).unlink(missing_ok=True)
        raise click.ClickException(
            f"{workflow} changed during sync or became unreadable{cause}; "
            "left it unchanged and discarded cached rules. Run sync again."
        )

    def sync_ref(selected_ref: str) -> bytes:
        validate_workflow()
        archive = _sync_workspace(
            project, repository, selected_ref, refresh, require_scripts
        )
        validate_workflow()
        return archive

    try:
        archive = sync_ref(ref)
    except _WorkspaceFetchError:
        if ref == original_ref:
            raise
        click.echo(
            f"Could not fetch asta-plugins@{ref}; keeping the workspace pin at "
            f"@{original_ref} and trying its rules",
            err=True,
        )
        return sync_ref(original_ref)
    if ref != original_ref:
        _write_pin(workflow, original, ref)
        click.echo(
            f"Moved the workspace pin in {workflow} from asta-plugins@{original_ref} "
            f"to @{ref}, the installed asta's release (not committed)",
            err=True,
        )
        # The workflow must not remain newer than the rules just loaded for it.
        (project / ".asta/cache/workspace.mk").touch()
    return archive


class _WorkspaceFetchError(click.ClickException):
    """The selected source could not be fetched and no matching cache exists."""


def _sync_workspace(
    project: Path, repository: str, ref: str, refresh: bool, require_scripts: bool
) -> bytes:
    """Prepare and validate the selected release before publishing a pin move."""
    if message := workspace_versions.pin_too_old(ref, WORKFLOW_FILE):
        raise click.ClickException(message)
    cli = workspace_versions.installed()
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
    except click.ClickException as exc:
        if cache_valid:
            _require_cli(target.read_bytes(), ref, cli)
            if require_scripts:
                _require_scripts(target.read_bytes(), state["scripts"], ref)
            target.touch()
            click.echo(
                f"Could not refresh asta-plugins@{ref}; using the cached copy", err=True
            )
            return cached_archive
        raise _WorkspaceFetchError(str(exc)) from exc
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
    root = workflow_root(project)
    workflow = root / WORKFLOW_FILE
    _reject_workflow_symlinks(workflow)
    _, ref = _source_from_workflow(workflow)
    target = workspace_versions.pin_target(ref, workspace_versions.installed())
    if target is None:
        click.echo(f"Pin asta-plugins@{ref} is current; nothing to do")
        return
    status = _git(root, "status", "--porcelain", "--", WORKFLOW_FILE)
    if status.returncode != 0:
        raise click.ClickException(
            f"Could not check the workflow's Git status: {status.stderr.strip()}"
        )
    if status.stdout.strip():
        raise click.ClickException(
            f"{WORKFLOW_FILE} has uncommitted changes; commit them first"
        )
    original = workflow.read_bytes()
    message = f"Move workspace pin to asta-plugins@{target}"
    head = _git(project, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise click.ClickException("Could not determine the workflow's Git HEAD")
    commit_started = False
    try:
        _write_pin(workflow, original, target)
        commit_started = True
        committed = _git(root, "commit", "-m", message, "--", WORKFLOW_FILE)
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


# Runs that build a commit (CI, the Overleaf sync runner) must build the pin it names.
UNATTENDED_ENV = ("ASTA_WORKSPACE_RESOLVED_SHA", "CI", "GITHUB_ACTIONS")


def _is_unattended() -> bool:
    return any(
        bool(os.environ.get(name))
        if name == "ASTA_WORKSPACE_RESOLVED_SHA"
        else os.environ.get(name, "").strip().casefold() not in ("", "0", "false")
        for name in UNATTENDED_ENV
    )


def _reject_workflow_symlinks(workflow: Path) -> None:
    root = workflow.parents[2]
    for relative in (".github", ".github/workflows", WORKFLOW_FILE):
        if (root / relative).is_symlink():
            raise click.ClickException(
                f"Workspace workflow path must not contain symlinks: {relative}"
            )


def _write_pin(workflow: Path, original: bytes, target: str) -> None:
    text = original.decode("utf-8")
    lines = text.splitlines(keepends=True)
    for index, match in _workflow_source_lines(text, workflow):
        start, end = match.span("ref")
        lines[index] = lines[index][:start] + target + lines[index][end:]
    _atomic_write(workflow, "".join(lines).encode("utf-8"))
    try:
        if _source_from_workflow(workflow)[1] != target:
            raise click.ClickException(f"Could not move the pin in {workflow}")
    except BaseException:
        _atomic_write(workflow, original)
        raise


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


def render_site(directory: Path, label: str, pages: list[str] | None = None) -> Path:
    if not directory.is_dir():
        raise click.ClickException(
            f"Project directory does not exist for {label}: {directory}"
        )
    click.echo(f"Rendering {label} with 'make render'", err=True)
    command = ["make", "-o", "workspace-assets", "-o", "workspace-viewers", "render"]
    if pages is not None:
        command += [
            "ASTA_WORKSPACE_RENDER_OUTPUT=_site",
            f"ASTA_WORKSPACE_RENDER_FILES={' '.join(pages)}",
        ]
    with preview_process(
        command,
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


# Rendered slide images, beside the comparison page in its site copy.
DECK_IMAGES = "what-changed-decks"


# A page that exists only in each temporary copy, rendered beside a
# slide-only edit so the report takes the site's look from the project's
# own config without running any project page.
THEME_PAGE = "asta-what-changed-look.qmd"
# `format: html` keeps it an ordinary page under a deck-format _metadata.yml.
THEME_PAGE_SOURCE = (
    "---\ntitle: What changed\nformat: html\n---\n\nThe site's look for What changed.\n"
)


def _add_theme_page(project: Path) -> tuple[Path, bytes] | None | bool:
    """Write the look page so Quarto renders it in this project.

    A project that lists its pages in `project.render` gets the page appended
    there. Returns the config to restore after the render, None when the
    config is unchanged, or False when the page can't be listed.
    """
    (project / THEME_PAGE).write_text(THEME_PAGE_SOURCE, encoding="utf-8")
    config = next(
        (
            project / name
            for name in ("_quarto.yml", "_quarto.yaml")
            if (project / name).is_file()
        ),
        None,
    )
    if config is None:
        return None
    original = config.read_bytes()
    try:
        data = yaml.safe_load(original)
    except yaml.YAMLError:
        return False
    settings = data.get("project") if isinstance(data, dict) else None
    listed = settings.get("render") if isinstance(settings, dict) else None
    if listed is None:
        return None
    if not isinstance(listed, list) or config.is_symlink():
        return False
    settings["render"] = [*listed, THEME_PAGE]
    config.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return config, original


_REDIRECT = re.compile(
    r"http-equiv\s*=\s*[\"']?refresh|window\.location", re.IGNORECASE
)
_STYLESHEET = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HREF = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _is_themed_page(page: Path, site: Path) -> bool:
    """Whether a built page is an ordinary site page whose stylesheets are present.

    A Quarto redirect home page, a deck, or a page whose site_libs a partial
    render left out cannot supply the site's theme.
    """
    if page.name.startswith("what-changed") or page.is_symlink() or not page.is_file():
        return False
    html = page.read_text(encoding="utf-8", errors="ignore")
    if 'class="reveal' in html:
        return False
    sheets = []
    for tag in _STYLESHEET.findall(html):
        href = _HREF.search(tag)
        if "stylesheet" in tag.lower() and href:
            sheets.append(href.group(1).split("?")[0].split("#")[0])
    local = [h for h in sheets if not re.match(r"(?i)^(?:[a-z]+:|//|/)", h)]
    if not local:
        return False
    root = site.resolve()
    for href in local:
        target = (page.parent / href).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return False
    return True


def _has_site_page(site: Path) -> bool:
    """Whether a built site has an ordinary page that carries the site's theme."""
    return any(
        _is_themed_page(page, site)
        for page in site.rglob("*.html")
        if DECK_IMAGES not in page.relative_to(site).parts
    )


def _is_ordinary_source(project: Path, name: str) -> bool:
    """Whether a selected source surely renders an ordinary page (not a deck).

    Unsure (a deck format from a directory's _metadata.yml, a redirect) means
    no, which only costs one extra page in the build.
    """
    texts = [project / name]
    for parent in Path(name).parents:
        texts += [
            project / parent / "_metadata.yml",
            project / parent / "_metadata.yaml",
        ]
    for path in texts:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "revealjs" in text or _REDIRECT.search(text):
            return False
    return True


def _has_deck(site: Path) -> bool:
    """Whether the rendered site holds a reveal.js deck, as the PR preview checks."""
    for page in site.rglob("*.html"):
        if page.is_file() and not page.is_symlink():
            if 'class="reveal' in page.read_text(encoding="utf-8", errors="ignore"):
                return True
    return False


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


IGNORED_RENDER_INPUTS = (".asta/cache", "_extensions")


def copy_ignored_render_inputs(project: Path, destination: Path) -> None:
    """Copy the project's git-ignored render inputs into a fresh copy.

    A scaffolded workspace ignores its synced make rules (`.asta/cache`) and
    fetched theme extensions, and `make -o workspace-assets` skips refetching
    them, so each copy takes them from the project every run. Files the copy
    already has (tracked at that commit) win; `.env*` files are never copied.
    """
    listed = subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "ls-files",
            "-z",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            *IGNORED_RENDER_INPUTS,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        raise click.ClickException(
            f"Could not list ignored render inputs: {listed.stderr.strip()}"
        )
    comparison = project / COMPARISON_DIR
    for name in filter(None, listed.stdout.split("\0")):
        source = project / name
        if (
            _is_env_file(name)
            or source == comparison
            or comparison in source.parents
            or Path(name).parts[:3] == (".asta", "cache", "what-changed")
            or Path(name).name.startswith(".what-changed-")
        ):
            continue
        target = destination / name
        if os.path.lexists(target) or not os.path.lexists(source):
            continue
        if source.is_dir() and not source.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)


def working_copy(repository: Path, prefix: str, destination: Path) -> Path:
    """Copy render inputs only: Git-visible files plus the synced workspace cache.

    Other ignored files (virtualenvs, outputs, caches) and untracked .env files
    stay out, so comparisons stay quick and do not duplicate secrets. The copy is
    a private shared clone: neither render registers a worktree or writes
    into the source repository. Ignored virtualenvs are not copied.
    """
    project = repository / prefix
    added = _git(
        repository,
        "clone",
        "--shared",
        "--no-checkout",
        str(repository),
        str(destination),
    )
    if added.returncode != 0:
        raise click.ClickException(
            f"Could not copy the working tree: {added.stderr.strip()}"
        )
    checked = _git(destination, "checkout", "--detach", "HEAD")
    if checked.returncode != 0:
        raise click.ClickException(
            f"Could not check out the working tree: {checked.stderr.strip()}"
        )
    entries = _git(repository, "ls-files", "--stage", "-z")
    if entries.returncode != 0:
        raise click.ClickException(
            f"Could not read the working-tree index: {entries.stderr.strip()}"
        )
    cleared = _git(destination, "read-tree", "--empty")
    if cleared.returncode != 0:
        raise click.ClickException(
            f"Could not clear the copied index: {cleared.stderr.strip()}"
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
    changed = _git(
        repository, "diff", "--name-only", "--no-renames", "-z", "HEAD", "--"
    )
    if changed.returncode != 0:
        raise click.ClickException(
            f"Could not list changed render inputs: {changed.stderr.strip()}"
        )
    files = dict.fromkeys(
        [name for name in changed.stdout.split("\0") if name] + untracked
    )
    click.echo(f"Overlaying {len(files)} changed/untracked render inputs", err=True)
    for name in files:
        source = repository / name
        target = destination / name
        if not os.path.lexists(source) or any(
            source == path or path in source.parents for path in live
        ):
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif os.path.lexists(target):
                target.unlink()
            continue
        if os.path.lexists(target):
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
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

    copy_ignored_render_inputs(project, destination / prefix)
    return destination / prefix


@contextmanager
def _comparison_directory():
    temporary = Path(tempfile.mkdtemp(prefix="asta-what-changed-"))
    try:
        yield temporary
    finally:
        try:
            with preview_cleanup():
                for entry in temporary.iterdir():
                    if entry.name in ("baseline", "working"):
                        continue
                    if entry.is_dir() and not entry.is_symlink():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
                # Leave failed clone cleanup visible rather than hiding it.
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


def _comparison_script():
    bundled = Path(__file__).parents[1] / "workspace_assets/what-changed.py"
    if bundled.is_file():
        return bundled
    return Path(__file__).parents[3] / ASSET_DIR / DIFF_SCRIPT


def _asset_script(name: str) -> Path:
    bundled = Path(__file__).parents[1] / "workspace_assets" / name
    if bundled.is_file():
        return bundled
    return Path(__file__).parents[3] / ASSET_DIR / name


def _commit_working_tree(project: Path) -> bool:
    """Point the throwaway copy's HEAD at a commit of its files.

    paper-preview.sh compares <base>..HEAD, which in the copy would miss the
    uncommitted edit. commit-tree runs no hooks and never signs.
    """
    added = _git(project, "add", "-A")
    tree = _git(project, "write-tree") if added.returncode == 0 else added
    if tree.returncode != 0:
        return False
    commit = _git(
        project,
        "-c",
        "user.name=asta",
        "-c",
        "user.email=asta@localhost",
        "-c",
        "commit.gpgSign=false",
        "commit-tree",
        tree.stdout.strip(),
        "-p",
        "HEAD",
        "-m",
        "What changed: working tree",
    )
    if commit.returncode != 0:
        return False
    moved = _git(project, "update-ref", "--no-deref", "HEAD", commit.stdout.strip())
    return moved.returncode == 0


def _paper_previews(project: Path, base: str, site: Path) -> None:
    """Build each changed paper's marked diff PDF into the site, as the PR preview does.

    Runs only where LaTeX is installed (e.g. the -tex dev container). As in the
    PR preview, a project's own scripts/<asset> takes precedence.
    """

    def script(name):
        own = project / "scripts" / name
        return own if own.is_file() else _asset_script(name)

    discovery = subprocess.run(
        [sys.executable, str(script("paper-discovery.py")), base],
        cwd=project,
        capture_output=True,
        text=True,
    )
    try:
        found = json.loads(discovery.stdout) if discovery.returncode == 0 else None
        papers, removed = list(found["papers"]), list(found["removed"])
        if not all(isinstance(d, str) for d in [*papers, *removed]):
            raise TypeError
    except (TypeError, KeyError, ValueError):
        click.echo(
            "Warning: could not discover paper projects, so no paper diff is shown"
            + (f" ({discovery.stderr.strip()})" if discovery.stderr.strip() else ""),
            err=True,
        )
        return
    if not papers and not removed:
        return
    # Discovery defines the paper roots/main files; dependency filtering must
    # happen before checking TeX or snapshotting the disposable working copy.
    from asta.commands.workspace_selection import paper_affected

    changed = _git(project, "diff", "--name-only", "--no-renames", "-z", base, "--")
    main_files = found.get("main_files", {})
    if changed.returncode == 0:
        prefix = _git(project, "rev-parse", "--show-prefix").stdout.strip()
        names = [
            p[len(prefix) :]
            for p in changed.stdout.split("\0")
            if p and p.startswith(prefix)
        ]
        names += _ls_files(project, "--others", "--exclude-standard")
        papers = [
            directory
            for directory in papers
            if directory not in main_files
            or paper_affected(project, directory, main_files[directory], names)
        ]
    if not papers and not removed:
        return
    missing = [tool for tool in ("latexmk", "latexdiff") if shutil.which(tool) is None]
    if missing:
        click.echo(
            f"Note: paper diffs are skipped because {' and '.join(missing)} "
            "isn't installed here; run in the -tex dev container to include them.",
            err=True,
        )
        return
    root = site / "paper-previews"
    if root.exists():
        click.echo(
            "Warning: the site already uses paper-previews/, so no paper diff is shown",
            err=True,
        )
        return
    if papers and not _commit_working_tree(project):
        click.echo(
            "Warning: could not snapshot the working tree, so paper diffs may "
            "miss uncommitted edits",
            err=True,
        )
    for directory in removed:
        (root / directory).mkdir(parents=True, exist_ok=True)
        (root / directory / "preview.json").write_text(
            '{"changed":true,"removed":true}\n'
        )
    for directory in papers:
        click.echo(f"Building the marked diff of {directory}", err=True)
        built = subprocess.run(
            ["bash", str(script("paper-preview.sh")), base, directory],
            cwd=project,
            capture_output=True,
            text=True,
        )
        if built.returncode != 0:
            out = root / directory
            out.mkdir(parents=True, exist_ok=True)
            tail = "\n".join((built.stdout + built.stderr).strip().splitlines()[-20:])
            (out / "build-failed.txt").write_text(tail + "\n")
            if not (out / "preview.json").is_file():
                (out / "preview.json").write_text('{"changed":false}\n')
            click.echo(
                f"Warning: the paper build for {directory} failed; "
                f"see {directory}/build in the comparison output",
                err=True,
            )


def _comparison_python(decks):
    """Live deck comparisons use the CLI's Python, with no browser dependency."""
    return [sys.executable], os.environ.copy()


def _default_comparison_ref(project):
    upstream = _git(
        project, "symbolic-ref", "-q", "refs/remotes/origin/HEAD"
    ).stdout.strip()
    configured = _git(project, "config", "--get", "init.defaultBranch").stdout.strip()
    for branch in (upstream, configured, "main", "master", "trunk"):
        if branch:
            # Qualify bare names: Git resolves a same-named tag before a branch.
            ref = branch if branch.startswith("refs/") else f"refs/heads/{branch}"
            base = _git(project, "merge-base", "HEAD", ref)
            if base.returncode == 0:
                return base.stdout.strip()
    raise click.ClickException("No default branch found; pass a Git ref")


def _changed_comparison_pages(project, baseline, ref):
    """Select dependencies from both trees; unknown inputs force a full render.

    No Quarto/setup or Makefile probe runs here. References are deliberately
    over-selected: a token appearing in prose is enough to count as a dependency.
    """
    from asta.commands.workspace_selection import select_pages

    diff = _git(project, "diff", "--name-only", "--no-renames", "-z", ref, "--")
    if diff.returncode:
        return None
    paths = diff.stdout.split("\0")
    paths += _ls_files(project, "--full-name", "--others", "--exclude-standard")
    prefix = _git(project, "rev-parse", "--show-prefix").stdout.strip()
    paths = [p[len(prefix) :] for p in paths if p and p.startswith(prefix)]
    return select_pages(project, baseline, paths)


def _comparison_inputs(project):
    """The files Quarto renders in this project, as `quarto inspect` lists them."""
    try:
        result = subprocess.run(
            ["quarto", "inspect", str(project)],
            capture_output=True,
            text=True,
            check=True,
        )
        return {
            Path(p).resolve() if Path(p).is_absolute() else (project / p).resolve()
            for p in json.loads(result.stdout)["files"]["input"]
        }
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        # An unavailable inspect must not hide any page; a render then fails loudly.
        return None


def _quarto_rendered(project, pages, inputs):
    """Selected pages that exist in this project and Quarto renders there."""
    return [
        name
        for name in pages
        if (project / name).is_file()
        and (inputs is None or (project / name).resolve() in inputs)
    ]


def _run_comparison(before, after, report, title, project, theme=None):
    """The single comparison engine for local and CI builds."""
    decks = _has_deck(before) or _has_deck(after)
    python, env = _comparison_python(decks)
    args = [
        *python,
        str(_comparison_script()),
        "--old",
        str(before),
        "--new",
        str(after),
        "--out",
        str(report),
        "--title",
        title,
        "--reserved-local-output",
    ]
    if theme is not None:
        args += ["--theme-root", str(theme)]
    if decks:
        args += [
            f"--render-decks={after / DECK_IMAGES}",
            f"--render-decks-url={DECK_IMAGES}",
        ]
    with preview_process(
        args,
        project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ) as process:
        for line in process.stdout:
            click.echo(line, nl=False, err=True)
        status = process.wait()
    if status:
        raise click.ClickException(
            f"{DIFF_SCRIPT} failed (exit {status}): {_comparison_script()}"
        )
    if report.is_symlink() or not report.is_file() or report.stat().st_size == 0:
        raise click.ClickException(f"{DIFF_SCRIPT} did not write nonempty HTML")
    return decks


def compare_built_sites(before: Path, after: Path, title: str | None = None):
    """Compare a published snapshot and PR build, publishing only on success."""
    with tempfile.TemporaryDirectory(
        prefix="asta-built-comparison-", dir=after.parent
    ) as directory:
        staged = Path(directory) / "site"
        shutil.copytree(after, staged, symlinks=True)
        report = staged / "what-changed.html"
        report.unlink(missing_ok=True)
        _run_comparison(
            before,
            staged,
            report,
            title or "Changes since published site",
            after.parent,
        )
        _publish(staged, after)
    click.echo(f"Wrote {after / 'what-changed.html'}")


@workspace.command("what-changed")
@click.argument("ref", required=False)
@click.option(
    "--project",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("."),
)
@click.option(
    "--before-site", type=click.Path(path_type=Path, file_okay=False, exists=True)
)
@click.option(
    "--after-site", type=click.Path(path_type=Path, file_okay=False, exists=True)
)
@click.option("--title", default=None)
@click.option(
    "--full", is_flag=True, help="Render the full site, including dependent pages."
)
@click.option(
    "--timings", is_flag=True, help="Print how long each step took, on stderr."
)
def what_changed(
    ref: str | None,
    project: Path,
    before_site: Path | None,
    after_site: Path | None,
    title: str | None,
    full: bool,
    timings: bool = False,
) -> None:
    """Show what changed in the rendered site since a git REF (tag, branch, commit).

    Renders REF and a private working-tree copy with the project's own 'make
    render' (only changed pages when possible, themed from ordinary pages rendered during this run; nothing is
    kept between runs) and compares them with the comparator the PR preview uses. The page is written to a copy of the rendered site under
    .asta/cache/what-changed/, which this command owns and replaces on each run.
    A live _site/ gets a redirect at _site/what-changed.html to this snapshot,
    replacing any project page of that name until the next render.
    Requires Git 2.30 or newer. Choose a trusted REF: its
    build code runs locally. The baseline contains only committed files.
    """
    global _step_times
    _step_times = [] if timings else None
    started = time.perf_counter()
    try:
        with preview_signals():
            if before_site is not None:
                if ref or after_site is None:
                    raise click.UsageError(
                        "--before-site requires --after-site and cannot be combined with REF"
                    )
                compare_built_sites(before_site.resolve(), after_site.resolve(), title)
            else:
                if after_site is not None:
                    raise click.UsageError("--after-site requires --before-site")
                compare_workspace(
                    ref or _default_comparison_ref(project), project, full=full
                )
    except KeyboardInterrupt:
        raise click.exceptions.Exit(130) from None
    except PreviewTerminated as exc:
        raise click.exceptions.Exit(128 + exc.signum) from None
    finally:
        if timings:
            _report_timings(time.perf_counter() - started)
        _step_times = None


_step_times: list[tuple[str, float]] | None = None


def _record(step: str, start: float) -> None:
    if _step_times is not None:
        _step_times.append((step, time.perf_counter() - start))


@contextmanager
def _timed(step: str):
    """Record STEP's wall time when --timings is on."""
    start = time.perf_counter()
    try:
        yield
    finally:
        _record(step, start)


def _report_timings(total: float) -> None:
    if not _step_times:
        return
    width = max(len(step) for step, _ in [*_step_times, ("other", 0)])
    click.echo("What changed timings:", err=True)
    for step, seconds in _step_times:
        click.echo(f"  {step:<{width}}  {seconds:7.2f} s", err=True)
    rest = total - sum(seconds for _, seconds in _step_times)
    click.echo(f"  {'other':<{width}}  {rest:7.2f} s", err=True)
    click.echo(f"  {'total':<{width}}  {total:7.2f} s", err=True)


def compare_workspace(ref: str, project: Path, *, full: bool = False) -> None:
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
            with _timed("check out baseline clone"):
                added = _git(
                    project,
                    "clone",
                    "--shared",
                    "--no-checkout",
                    repository.stdout.rstrip("\n"),
                    str(baseline),
                )
                if added.returncode == 0:
                    added = _git(
                        baseline, "checkout", "--detach", commit.stdout.strip()
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
            copy_ignored_render_inputs(project, baseline_project)
            with _timed("find changed pages"):
                pages = (
                    None
                    if full
                    else _changed_comparison_pages(project, baseline_project, ref)
                )
            # Both sides are fresh, private builds. Never borrow a preview:
            # a source edit can arrive while that preview is still rendering.
            theme = None
            with _timed("copy working tree"):
                copied_project = working_copy(
                    Path(repository.stdout.rstrip("\n")),
                    prefix.stdout.rstrip("\n"),
                    tmp / "working",
                )
            before_pages = after_pages = theme_pages = []
            restore = []
            if pages:
                # Ask Quarto which files each side renders before rendering any:
                # a README or notes file must never reach `quarto render`.
                with _timed("list rendered files (quarto inspect)"):
                    with _parallel_builds() as pool:
                        before_inputs = pool.submit(
                            _comparison_inputs, baseline_project
                        )
                        after_inputs = pool.submit(_comparison_inputs, copied_project)
                        before_inputs = before_inputs.result()
                        after_inputs = after_inputs.result()
                before_pages = _quarto_rendered(baseline_project, pages, before_inputs)
                after_pages = _quarto_rendered(copied_project, pages, after_inputs)
                # A slide-only edit selects no ordinary page; add one to both
                # builds so each side's site carries the site's look.
                if (before_pages or after_pages) and not any(
                    _is_ordinary_source(side, name)
                    for side, names in (
                        (baseline_project, before_pages),
                        (copied_project, after_pages),
                    )
                    for name in names
                ):
                    added = [
                        _add_theme_page(side)
                        for side in (baseline_project, copied_project)
                    ]
                    restore = [a for a in added if isinstance(a, tuple)]
                    if False in added:
                        click.echo(
                            "Warning: could not add a page for the site's look to "
                            "project.render in _quarto.yml, so What changed may "
                            "look unstyled.",
                            err=True,
                        )
                    else:
                        theme_pages = [THEME_PAGE]

            def render_side(project_dir, label, selected):
                if pages is None:
                    return render_site(project_dir, label)
                if not selected:
                    site = project_dir / "_site"
                    site.mkdir(exist_ok=True)
                    return site
                return render_site(project_dir, label, selected)

            # Record the enclosing wall time, rather than adding overlapping
            # durations and reporting a negative remainder in --timings.
            with _timed("render before and after (parallel)"):
                with _parallel_builds() as pool:
                    before = pool.submit(
                        render_side,
                        baseline_project,
                        ref,
                        list(dict.fromkeys([*before_pages, *theme_pages])),
                    )
                    after = pool.submit(
                        render_side,
                        copied_project,
                        "the working tree",
                        list(dict.fromkeys([*after_pages, *theme_pages])),
                    )
                    old_site = before.result()
                    new_site = after.result()
            if theme_pages:
                theme = tmp / "theme"
                theme.mkdir()
                themed = False
                for name in theme_pages:
                    # Take the look from the working tree's build, else the
                    # base's; drop the page from both so it isn't compared.
                    for site in (new_site, old_site):
                        built = site / Path(name).with_suffix(".html")
                        if built.is_file() and not built.is_symlink():
                            if not themed and _is_themed_page(built, site):
                                themed = True
                                shutil.move(built, theme / built.name)
                            else:
                                built.unlink()
                if not themed:
                    click.echo(
                        "Warning: no rendered page carries the site's theme "
                        "(a redirect home page or missing stylesheets), so "
                        "What changed may look unstyled.",
                        err=True,
                    )
            if pages:
                for side in (baseline_project, copied_project):
                    (side / THEME_PAGE).unlink(missing_ok=True)
                for config, original in restore:
                    config.write_bytes(original)
            with _timed("build paper diffs"):
                _paper_previews(copied_project, commit.stdout.strip(), new_site)
            # The page sits at the root of a site copy so its relative links
            # to changed pages resolve, as in the PR preview.
            if (project / ".asta").is_symlink() or owned.parent.is_symlink():
                raise click.ClickException("Workspace cache must not be a symlink")
            owned.parent.mkdir(parents=True, exist_ok=True)
            staged = Path(tempfile.mkdtemp(prefix=".what-changed-", dir=owned.parent))
            try:
                stage_start = time.perf_counter()
                # The baseline's theme pages link REF's site_libs.
                base_libs = old_site / "site_libs"
                if theme_pages and base_libs.is_dir() and not base_libs.is_symlink():
                    shutil.copytree(base_libs, staged / "site_libs", symlinks=True)
                # Copy entries, not the root's metadata: staging stays 0700.
                for entry in new_site.iterdir():
                    if entry.is_dir() and not entry.is_symlink():
                        shutil.copytree(
                            entry,
                            staged / entry.name,
                            symlinks=True,
                            dirs_exist_ok=True,
                        )
                    else:
                        shutil.copy2(entry, staged / entry.name, follow_symlinks=False)
                _record("stage site copy", stage_start)
                report = staged / "what-changed.html"
                report.unlink(missing_ok=True)
                with _timed("compare pages and picture slides"):
                    decks = _run_comparison(
                        old_site,
                        new_site,
                        report,
                        f"Changes since {ref}",
                        project,
                        theme,
                    )
                deck_images = new_site / DECK_IMAGES
                if decks and deck_images.is_dir() and not deck_images.is_symlink():
                    shutil.rmtree(staged / DECK_IMAGES, ignore_errors=True)
                    shutil.copytree(deck_images, staged / DECK_IMAGES, symlinks=True)
                try:
                    with _timed("publish snapshot"):
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
                for directory in (tmp / "working", baseline):
                    if directory.exists():
                        shutil.rmtree(directory)
    page = owned / "what-changed.html"
    if (project / "_site").is_dir():
        link = project / "_site/what-changed-snapshot"
        if link.exists() and not link.is_symlink():
            raise click.ClickException(
                "_site/what-changed-snapshot is reserved for the comparison"
            )
        link.unlink(missing_ok=True)
        link.symlink_to(owned, target_is_directory=True)
        _atomic_write(
            project / "_site/what-changed.html",
            b'<meta http-equiv="refresh" content="0;url=what-changed-snapshot/what-changed.html"><a href="what-changed-snapshot/what-changed.html">What changed</a>',
        )
        if recorded_preview(project):
            click.echo(f"Live preview: {preview_url(os.environ)}what-changed.html")
    if (project / "_site").is_dir():
        # The independent snapshot remains available after a preview rebuild.
        click.echo(
            f"Preview comparison: {preview_url(os.environ, WHAT_CHANGED_PORT)}what-changed.html"
        )
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


# A signal reaches the main thread, while parallel build processes belong
# to worker threads. Track them so shutdown kills both process groups before
# waiting for the workers, including a process spawned during cancellation.
_parallel_state = None


@contextmanager
def _parallel_builds():
    global _parallel_state
    state = (threading.Event(), threading.Lock(), [])
    _parallel_state = state
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    try:
        yield pool
    except BaseException:
        state[0].set()
        with state[1]:
            processes = list(state[2])
        for process in processes:
            if process.poll() is None:
                stop_preview(process, signal.SIGINT)
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        _parallel_state = None


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
        state = _parallel_state
        if state is not None:
            with state[1]:
                state[2].append(process)
            if state[0].is_set():
                stop_preview(process, signal.SIGINT)
                raise KeyboardInterrupt
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
