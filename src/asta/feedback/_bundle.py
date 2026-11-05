"""Package a local feedback directory into a single gzip-tar bundle.

The ``feedback`` skill populates a local directory with a ``FEEDBACK.md``
narrative and optional supporting files (agent-generated reports that
illustrate the narrative). The user reviews that directory, then
``asta feedback submit <dir>`` bundles it and uploads it in one shot.

This module owns the *client-side* packaging: validation, size gates, a
self-describing ``manifest.json``, and the gzip-tar bytes. It is stdlib-only
(no new deps) and does no network I/O — see ``asta.feedback._client`` for
the presigned-upload transport.

The submitter's identity is *not* recorded here; the Gateway derives it from
the caller's JWT when it mints the submission id, keeping this bundle free of
local user/host details.
"""

from __future__ import annotations

import gzip
import io
import json
import mimetypes
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path

from asta import __version__

# The narrative report is the record (it replaces conversation transcripts),
# so it is required at the root of the submission directory.
NARRATIVE_FILENAME = "FEEDBACK.md"

# Attachments are small agent-generated reports, not datasets. Gate generously
# but bound it. Overridable for the rare large report.
_DEFAULT_MAX_FILE_MB = 25
_DEFAULT_MAX_TOTAL_MB = 100

# Skip VCS/editor/cache cruft the skill may leave in the directory.
_EXCLUDED_NAMES = {".git", ".DS_Store", "__pycache__", ".ipynb_checkpoints"}

# mimetypes doesn't reliably know Markdown; pin the few we care about.
_CONTENT_TYPE_OVERRIDES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


@dataclass(frozen=True)
class FileEntry:
    """One file staged into the bundle, described relative to the root."""

    path: str  # POSIX-style path relative to the submission directory
    size: int
    content_type: str


@dataclass(frozen=True)
class Bundle:
    """A packaged submission ready to upload."""

    data: bytes  # gzip-tar bytes
    manifest: dict
    files: list[FileEntry]
    total_bytes: int  # sum of raw (uncompressed) file sizes

    @property
    def num_files(self) -> int:
        return len(self.files)


def _max_bytes(env_var: str, default_mb: int) -> int:
    raw = os.environ.get(env_var)
    if not raw:
        return default_mb * 1024 * 1024
    try:
        return int(float(raw) * 1024 * 1024)
    except ValueError as e:
        raise ValueError(f"{env_var} must be a number of megabytes, got {raw!r}") from e


def _content_type(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in _CONTENT_TYPE_OVERRIDES:
        return _CONTENT_TYPE_OVERRIDES[ext]
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _collect_files(directory: Path) -> list[FileEntry]:
    """Gather regular files under ``directory``, skipping dot/cruft paths.

    Symlinks are ignored (only regular files are packaged) to avoid escaping
    the submission directory.
    """
    entries: list[FileEntry] = []
    for root, dirs, files in os.walk(directory):
        # Prune excluded and hidden directories in place so os.walk skips them.
        dirs[:] = [
            d for d in dirs if d not in _EXCLUDED_NAMES and not d.startswith(".")
        ]
        for filename in sorted(files):
            if filename in _EXCLUDED_NAMES or filename.startswith("."):
                continue
            abspath = Path(root) / filename
            if abspath.is_symlink() or not abspath.is_file():
                continue
            relpath = abspath.relative_to(directory).as_posix()
            entries.append(
                FileEntry(
                    path=relpath,
                    size=abspath.stat().st_size,
                    content_type=_content_type(filename),
                )
            )
    entries.sort(key=lambda e: e.path)
    return entries


def build_bundle(directory: str | os.PathLike) -> Bundle:
    """Validate ``directory`` and package it into a gzip-tar ``Bundle``.

    Requires a ``FEEDBACK.md`` at the root. All other regular files are
    included as supporting attachments. A ``manifest.json`` describing the
    contents is added at the root of the archive.

    Raises:
        FileNotFoundError: the directory or the required narrative is missing.
        ValueError: an empty submission, or a per-file / total size gate is
            exceeded.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Not a directory: {directory}")

    narrative = directory / NARRATIVE_FILENAME
    if not narrative.is_file():
        raise FileNotFoundError(
            f"Missing required {NARRATIVE_FILENAME} in {directory}. "
            "The narrative report is the body of the submission."
        )

    files = _collect_files(directory)
    if not files:
        raise ValueError(f"No files to submit in {directory}.")

    max_file = _max_bytes("ASTA_FEEDBACK_MAX_FILE_MB", _DEFAULT_MAX_FILE_MB)
    max_total = _max_bytes("ASTA_FEEDBACK_MAX_TOTAL_MB", _DEFAULT_MAX_TOTAL_MB)

    total = 0
    for entry in files:
        if entry.size > max_file:
            raise ValueError(
                f"{entry.path} is {entry.size / 1024 / 1024:.1f} MiB; the "
                f"per-file limit is {max_file // 1024 // 1024} MiB "
                "(set ASTA_FEEDBACK_MAX_FILE_MB to raise it)."
            )
        total += entry.size
    if total > max_total:
        raise ValueError(
            f"Submission is {total / 1024 / 1024:.1f} MiB; the total limit is "
            f"{max_total // 1024 // 1024} MiB "
            "(set ASTA_FEEDBACK_MAX_TOTAL_MB to raise it)."
        )

    manifest = {
        "narrative": NARRATIVE_FILENAME,
        "files": [
            {"path": e.path, "size": e.size, "content_type": e.content_type}
            for e in files
        ],
        "total_bytes": total,
        "client": {"tool": "asta-cli", "version": __version__},
    }

    data = _write_archive(directory, files, manifest)
    return Bundle(data=data, manifest=manifest, files=files, total_bytes=total)


def _write_archive(directory: Path, files: list[FileEntry], manifest: dict) -> bytes:
    """Serialize ``files`` + ``manifest.json`` into deterministic gzip-tar bytes.

    Member metadata (mtime, uid/gid, ownership) is normalized and the gzip
    header mtime is zeroed so the same input always yields the same bytes and
    no local user/host details leak into the upload.
    """

    def _tarinfo(name: str, size: int) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name=name)
        info.size = size
        info.mtime = 0
        info.mode = 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
            tar.addfile(
                _tarinfo("manifest.json", len(manifest_bytes)),
                io.BytesIO(manifest_bytes),
            )
            for entry in files:
                with open(directory / entry.path, "rb") as f:
                    body = f.read()
                tar.addfile(_tarinfo(entry.path, len(body)), io.BytesIO(body))
    return raw.getvalue()
