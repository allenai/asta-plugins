"""Copy a paper between the workspace and Overleaf's Git integration."""

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import click

CONFIG = "overleaf.json"
RECOVERY = (
    "https://github.com/allenai/asta-plugins/blob/main/"
    "plugins/asta-tools/skills/workspace/workflows/overleaf-recovery.md"
)
SHA = re.compile(r"[0-9a-f]{40}")
# Format of the sync state runners share: overleaf.json, the record and lock refs,
# and the sync PR. Bump FORMAT only when an older CLI would misread the state, and
# set FORMAT_RELEASE to the first asta release that reads it. Unversioned state is
# format 1.
FORMAT = 1
FORMAT_RELEASE = "0.116.0"
RELEASE = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}")
FULL_OID = r"[0-9a-f]{40}(?:[0-9a-f]{24})?"
# Git's `rev-parse --local-env-vars` list, plus the namespace override.
LOCAL_GIT_ENV = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_INTERNAL_SUPER_PREFIX",
}


def git_environment() -> dict:
    # Local Git hooks need no Overleaf token; tracing can log authorization headers.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in LOCAL_GIT_ENV | {"OVERLEAF_TOKEN"}
        and not key.startswith("GIT_TRACE")
        and key != "GIT_CURL_VERBOSE"
    }
    if not sys.stdin.isatty():
        env["GIT_TERMINAL_PROMPT"] = "0"
        # Empty overrides also suppress core.askPass and SSH_ASKPASS fallbacks.
        env["GIT_ASKPASS"] = ""
    return env


class SyncError(click.ClickException):
    """A scheduler can report each refusal as one line with a recovery reference."""

    def __init__(self, message: str, *, recovery: str = "local-git-failure"):
        message = " ".join(message.splitlines())
        if RECOVERY not in message:
            message = f"{message} Recovery: {RECOVERY}#{recovery}"
        super().__init__(message)


class GitCommandError(click.ClickException):
    def __init__(self, message: str, returncode: int):
        super().__init__(message)
        self.returncode = returncode


class OriginAccessError(SyncError):
    """Transport or discovery failed while fetching reviewed workspace history."""


class ProjectURLError(SyncError):
    """A supplied project URL is outside the supported Overleaf Git format."""


def git_bytes(
    *args: str, cwd: Path, env: dict | None = None, input: bytes | None = None
) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=git_environment() if env is None else env,
        capture_output=True,
        input=input,
    )
    if result.returncode:
        index = 0
        while index < len(args) and args[index].startswith("-"):
            index += 2 if args[index] == "-c" else 1
        operation = args[index] if index < len(args) else "command"
        # Diagnostics may contain URLs or credential-helper output, so never echo them.
        stderr = result.stderr.lower()
        if operation == "push" and (
            b"hook declined" in stderr or b"pre-push" in stderr
        ):
            raise SyncError(
                "Workspace pre-push hook failed; nothing pushed. "
                "Check the hook against the exported paper directory and Overleaf remote.",
                recovery="git-hooks-and-signing",
            )
        if operation in ("clone", "push") and (
            re.search(rb"(?:http(?:/[\d.]+)?\s+|returned error:\s*)401\b", stderr)
            or b"authentication failed" in stderr
            or b"could not read username" in stderr
            or b"could not read password" in stderr
        ):
            raise SyncError(
                "Overleaf authentication failed. Check OVERLEAF_TOKEN or your Git credential helper.",
                recovery="overleaf-authentication",
            )
        if operation in ("clone", "push") and re.search(
            rb"(?:http(?:/[\d.]+)?\s+|returned error:\s*)403\b", stderr
        ):
            raise SyncError(
                "Overleaf access denied. Check your token and access to this project.",
                recovery="overleaf-authentication",
            )
        if operation == "push" and (
            re.search(
                rb"^\s*! \[rejected\] [^\r\n]+ \((?:non-fast-forward|fetch first)\)\s*$",
                stderr,
                re.M,
            )
        ):
            raise SyncError(
                "Overleaf changed while publishing; nothing pushed. "
                "Run `asta workspace overleaf pull`, review the changes in a PR, "
                "then publish again.",
                recovery="overleaf-edits-need-review",
            )
        if operation == "push" and b"rejected" in stderr:
            raise SyncError(
                f"git {operation} was rejected. Check access and the remote state.",
                recovery="overleaf-connection",
            )
        if operation in ("clone", "push"):
            raise SyncError(
                f"git {operation} failed (exit {result.returncode}). "
                "Check your Overleaf credentials, project access, network and remote state."
                + (
                    " Also check workspace pre-push hooks."
                    if operation == "push"
                    else ""
                ),
                recovery="overleaf-connection",
            )
        if operation == "commit":
            raise SyncError(
                f"git commit failed (exit {result.returncode}). "
                "Check workspace commit hooks and signing settings. "
                "Hooks run in the exported paper directory, not the full workspace.",
                recovery="git-hooks-and-signing",
            )
        raise GitCommandError(
            f"git {operation} failed (exit {result.returncode}).", result.returncode
        )
    return result.stdout


def git(*args: str, **kwargs) -> str:
    return os.fsdecode(git_bytes(*args, **kwargs)).rstrip("\n")


def publish_message(reviewed: str) -> str:
    return f"Publish workspace commit {reviewed}"


def publish_source(message: str) -> str | None:
    """The workspace commit named by a ``publish`` message, if any."""
    message = message.strip()
    source = message.rsplit(" ", 1)[-1]
    if re.fullmatch(FULL_OID, source) and message == publish_message(source):
        return source
    return None


def resolve_commit(repo: Path, revision: str) -> str | None:
    try:
        return git(
            "rev-parse",
            "--verify",
            "-q",
            "--end-of-options",
            f"{revision}^{{commit}}",
            cwd=repo,
        )
    except GitCommandError as exc:
        if exc.returncode != 1:
            raise
        return None


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    try:
        git("merge-base", "--is-ancestor", "--", ancestor, descendant, cwd=repo)
        return True
    except GitCommandError as exc:
        if exc.returncode != 1:
            raise
        return False


def hook_settings(root: Path) -> list[str]:
    hooks = (root / git("rev-parse", "--git-path", "hooks", cwd=root)).resolve()
    return ["-c", f"core.hooksPath={hooks}"]


def commit_settings(root: Path) -> list[str]:
    options = hook_settings(root)
    settings = {}
    for key in (
        "commit.gpgsign",
        "user.signingkey",
        "gpg.format",
        "gpg.program",
        "gpg.openpgp.program",
        "gpg.x509.program",
        "gpg.ssh.program",
        "gpg.ssh.defaultKeyCommand",
    ):
        result = subprocess.run(
            ["git", "config", "--get", key],
            cwd=root,
            env=git_environment(),
            capture_output=True,
        )
        if result.returncode == 0:
            value = os.fsdecode(result.stdout).rstrip("\n")
            settings[key] = value
        elif result.returncode != 1:
            raise SyncError(
                "Could not read workspace Git commit settings. Check Git configuration and repository permissions, then retry.",
                recovery="local-git-failure",
            )
    for key, value in settings.items():
        # OpenPGP/X.509 keys are backend identifiers; only SSH file keys need rebasing.
        if (
            key == "user.signingkey"
            and settings.get("gpg.format") == "ssh"
            and not value.startswith(("key::", "ssh-"))
        ) or (key.endswith(".program") and "/" in value):
            value = str((root / Path(value).expanduser()).resolve())
        options.extend(["-c", f"{key}={value}"])
    return options


def validate_url(url: str | None) -> str:
    match = re.fullmatch(
        r"https://(?:git@)?git\.overleaf\.com/([A-Za-z0-9]+)(?:\.git)?/?", url or ""
    )
    if not match:
        raise ProjectURLError(
            "Give the project's Git URL: https://git.overleaf.com/<project-id>.",
            recovery="project-url",
        )
    return f"https://git.overleaf.com/{match[1]}"


@contextmanager
def credentials():
    """Answer Git's prompt from OVERLEAF_TOKEN, else leave normal credential helpers in place."""
    env = git_environment()
    token = os.environ.get("OVERLEAF_TOKEN")
    if not token:
        yield env, []
        return
    with tempfile.TemporaryDirectory() as tmp:
        token_file = Path(tmp) / "token"
        token_file.touch(mode=stat.S_IRUSR | stat.S_IWUSR)
        token_file.write_text(token, encoding="utf-8")
        askpass = Path(tmp) / "askpass"
        askpass.write_text(
            '#!/bin/sh\ncat "$(dirname "$0")/token"\n',
            encoding="utf-8",
        )
        askpass.chmod(stat.S_IRWXU)
        env.update(GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT="0")
        # An empty helper list stops Git from storing the token anywhere.
        yield env, ["-c", "credential.helper="]


def clone(url: str, dest: Path) -> str:
    with credentials() as (env, options):
        git(
            *options,
            "clone",
            "--quiet",
            "--no-tags",
            "--no-checkout",
            url.replace("https://", "https://git@", 1),
            str(dest),
            cwd=dest.parent,
            env=env,
        )
    try:
        return git("rev-parse", "--verify", "HEAD", cwd=dest)
    except click.ClickException:
        raise SyncError(
            "Overleaf project has no commits to sync. Add an initial paper file in Overleaf, then retry.",
            recovery="empty-overleaf-project",
        ) from None


def push(
    repo: Path,
    root: Path,
    *,
    expected_commit: str | None = None,
    reviewed_ref: str | None = None,
) -> None:
    with credentials() as (env, options):
        if expected_commit is not None:
            require_expected_tip(root, expected_commit, reviewed_ref)
        git(
            *options,
            *hook_settings(root),
            "push",
            "--quiet",
            "origin",
            "HEAD",
            cwd=repo,
            env=env,
        )


def tree(repo: Path, revision: str, prefix: str = "") -> dict[str, tuple[str, str]]:
    out = git_bytes(
        "--literal-pathspecs",
        "ls-tree",
        "-r",
        "-z",
        revision,
        "--",
        prefix or ".",
        cwd=repo,
    )
    result = {}
    for entry in filter(None, out.split(b"\0")):
        meta, path = entry.split(b"\t", 1)
        mode, _, blob = meta.decode().split()
        result[os.fsdecode(path)[len(prefix) :]] = (mode, blob)
    return result


def refuse(name: str, reason: str) -> None:
    raise SyncError(
        f"Overleaf sync copies plain files only: {name!r} {reason}. "
        "Remove it or sync this paper by hand.",
        recovery="plain-files-only",
    )


def is_git_path(part: str) -> bool:
    # Git's HFS+ ignorable characters and NTFS aliases of its administrative name.
    normalized = re.sub(r"[\u200c-\u200f\u202a-\u202e\u206a-\u206f\ufeff]", "", part)
    return bool(re.match(r"^(?:\.git|git~1)[ .]*(?:$|[:\\])", normalized.casefold()))


def check_paths(names) -> None:
    seen = {}
    names = set(names)
    for name in names:
        parts = re.split(r"[/\\]", name)
        if any(part in ("", ".", "..") or is_git_path(part) for part in parts) or any(
            ord(c) < 32 or 127 <= ord(c) <= 159 for c in name
        ):
            refuse(name, "has an unsafe path")
        for end in range(1, len(parts) + 1):
            prefix = "/".join(parts[:end])
            key = unicodedata.normalize("NFC", prefix).casefold()
            other = seen.setdefault(key, prefix)
            if other != prefix:
                refuse(
                    name,
                    f"differs from {other} only in letter case or Unicode normalization",
                )
            if end < len(parts) and prefix in names:
                refuse(name, f"uses file {prefix} as a directory")


def read_plain_files(repo: Path, revision: str, prefix: str = "") -> dict[str, bytes]:
    """Read every file before anything is written, refusing what sync can't copy as-is."""
    result = {}
    entries = tree(repo, revision, prefix)
    check_paths(entries)
    for name, (mode, blob) in entries.items():
        if mode != "100644":
            refuse(name, "is executable, a symlink or a submodule")
        if (
            unicodedata.normalize("NFC", name.rsplit("/", 1)[-1]).casefold()
            == ".gitattributes"
        ):
            refuse(name, "can change file contents in transit")
        data = git_bytes("cat-file", "blob", blob, cwd=repo)
        if data.startswith(b"version https://git-lfs.github.com/spec/"):
            refuse(name, "is a Git LFS pointer")
        result[name] = data
    return result


def check_ignore_files(names) -> None:
    for name in names:
        if (
            unicodedata.normalize("NFC", name.rsplit("/", 1)[-1]).casefold()
            == ".gitignore"
        ):
            raise SyncError(
                f"Overleaf sync refuses {name!r}: ignore rules can hide imported sources. "
                "Keep ignore rules in the workspace root.",
                recovery="ignore-rules",
            )


def resolve(project: Path, directory: str) -> tuple[Path, Path, str]:
    root = Path(git("rev-parse", "--show-toplevel", cwd=project)).resolve()
    try:
        git("rev-parse", "--verify", "-q", "HEAD", cwd=root)
    except click.ClickException:
        raise SyncError(
            "Commit the workspace's initial files before syncing with Overleaf.",
            recovery="initial-workspace-commit",
        ) from None
    if Path(directory).is_absolute():
        raise SyncError(
            "--dir must be relative to the workspace. Use a subdirectory such as --dir paper.",
            recovery="paper-directory",
        )
    candidate = root / directory
    for path in (candidate, *candidate.parents):
        if path == root:
            break
        if path.is_symlink():
            refuse(directory, "uses a symlinked directory")
    paper = candidate.resolve()
    if root not in paper.parents:
        raise SyncError(
            "--dir must be a subdirectory of the workspace. Use --dir paper or another paper subdirectory.",
            recovery="paper-directory",
        )
    relative = paper.relative_to(root).as_posix()
    check_paths([relative])
    for option in ("--absolute-git-dir", "--git-common-dir"):
        metadata = (root / git("rev-parse", option, cwd=root)).resolve()
        if paper == metadata or metadata in paper.parents or paper in metadata.parents:
            refuse(directory, "overlaps Git administrative files")
    return root, paper, relative + "/"


# Untracked outputs of a local LaTeX build (LaTeX Workshop, latexmk) never block sync.
BUILD_SUFFIXES = (
    ".aux",
    ".bbl",
    ".bcf",
    ".blg",
    ".dvi",
    ".fdb_latexmk",
    ".fls",
    ".lof",
    ".log",
    ".lot",
    ".nav",
    ".out",
    ".run.xml",
    ".snm",
    ".synctex.gz",
    ".synctex(busy)",
    ".toc",
    ".xdv",
)


def is_build_output(path: Path) -> bool:
    name = path.name
    if name.endswith(BUILD_SUFFIXES):
        return True
    # A PDF is a build output only when it sits next to the .tex it was built from.
    return name.endswith(".pdf") and path.with_name(name[:-4] + ".tex").is_file()


def require_clean(root: Path, *paths: Path) -> None:
    status = git_bytes(
        "--literal-pathspecs",
        "status",
        "--porcelain",
        "-z",
        "--untracked-files=all",
        "--",
        *map(str, paths),
        cwd=root,
    )
    for entry in status.split(b"\0"):
        if not entry:
            continue
        if entry.startswith(b"?? ") and is_build_output(root / os.fsdecode(entry[3:])):
            continue
        names = ", ".join(p.relative_to(root).as_posix() for p in paths)
        raise SyncError(
            f"Commit or discard local changes in {names} first.",
            recovery="local-changes",
        )


def require_visible(root: Path, paths) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-z", "--stdin"],
        input=b"\0".join(os.fsencode(path) for path in paths) + b"\0",
        cwd=root,
        env=git_environment(),
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise SyncError(
            "Could not check Git ignore rules; nothing copied. Check Git configuration and repository permissions, then retry.",
            recovery="ignore-rules",
        )
    if result.stdout:
        name = Path(os.fsdecode(result.stdout.split(b"\0", 1)[0]))
        raise SyncError(
            f"{name.relative_to(root)} is ignored by Git. Adjust the ignore rules "
            "so imported sources and sync metadata can be committed; nothing copied.",
            recovery="ignore-rules",
        )


class FormatError(SyncError):
    """Shared state whose format cannot safely be interpreted or overwritten."""


class NewerFormatError(FormatError):
    """Shared sync state written by a newer asta than this one."""


def malformed_format(where: str) -> FormatError:
    return FormatError(
        f"{where} has a malformed sync format stamp; restore it from its history and retry.",
        recovery="malformed-sync-format",
    )


def format_stamp() -> dict:
    return {"format": FORMAT, "requires_asta": FORMAT_RELEASE}


def check_format(version, release, where: str) -> None:
    """Stop before reading state in a format this CLI does not understand."""
    # Callers default only an absent field to legacy format 1; null is invalid.
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise malformed_format(where)
    if version > FORMAT:
        needed = (
            f"asta {release} or later"
            if isinstance(release, str) and RELEASE.fullmatch(release)
            else "a newer asta release"
        )
        raise NewerFormatError(
            f"{where} uses Overleaf sync format {version}, but this asta reads up "
            f"to format {FORMAT}. Upgrade to {needed} and retry; nothing changed.",
            recovery="newer-sync-format",
        )


def load_config(paper: Path) -> dict:
    path = paper / CONFIG
    if path.is_symlink():
        refuse(CONFIG, "is a symlink")
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(config, dict):
            check_format(
                config.get("format", 1), config.get("requires_asta"), str(path)
            )
        if not isinstance(config, dict) or not isinstance(config.get("base"), str):
            raise ValueError("expected an object with a base commit")
        if not SHA.fullmatch(config["base"]) or not isinstance(config.get("url"), str):
            raise ValueError("expected a base commit and project URL")
        config["url"] = validate_url(config["url"])
        return config
    except FormatError:
        raise
    except (ValueError, OSError, click.ClickException):
        raise SyncError(
            f"Invalid sync record: {path}. Restore its project URL and base commit from Git.",
            recovery="paper-configuration",
        ) from None


def save_config(paper: Path, url: str, base: str) -> None:
    path = paper / CONFIG
    if path.is_symlink():
        refuse(CONFIG, "is a symlink")
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = None
    if isinstance(current, dict):
        check_format(current.get("format", 1), current.get("requires_asta"), str(path))
    # Preserve bytes, including extra keys and formatting, when nothing changed.
    # Stamping alone must not turn an unchanged unversioned config into a diff.
    if (
        isinstance(current, dict)
        and (current.get("url"), current.get("base")) == (url, base)
        and current.get("format", FORMAT) == FORMAT
    ):
        return
    text = json.dumps({**format_stamp(), "url": url, "base": base}, indent=2) + "\n"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / CONFIG).write_text(text, encoding="utf-8")


def write_files(contents: dict[str, bytes], dest: Path) -> None:
    for name, data in contents.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


# Also refuse retained labels from hand-edited diff3 blocks, although our merges
# use --no-diff3 and never generate a base section.
MARKER = re.compile(
    rb"^(?:<<<<<<< workspace|\|{7} last sync|>>>>>>> overleaf)\r?$", re.M
)
MERGE_SUFFIXES = {
    ".tex",
    ".ltx",
    ".bib",
    ".bst",
    ".bbx",
    ".cbx",
    ".sty",
    ".cls",
    ".clo",
    ".def",
    ".cfg",
    ".dtx",
    ".ins",
    ".tikz",
    ".pgf",
    ".csv",
    ".tsv",
    ".dat",
    ".txt",
    ".md",
}
# Distinct from the exit status 1 used for errors, so callers can detect conflicts.
CONFLICT_EXIT = 3


def merge_text(
    name: str, ours: bytes, base: bytes, theirs: bytes
) -> tuple[bytes | None, bool]:
    """Three-way merge of known text sources; None when unsuitable for line merging."""
    # ASCII assets such as PDFs and EPS can contain no NUL and still be unsafe to merge.
    if Path(name).suffix.lower() not in MERGE_SUFFIXES or any(
        b"\0" in data for data in (ours, base, theirs)
    ):
        return None, False
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for label, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            path = Path(tmp) / label
            path.write_bytes(data)
            paths.append(str(path))
        result = subprocess.run(
            [
                "git",
                "merge-file",
                "--no-diff3",
                "-p",
                "-L",
                "workspace",
                "-L",
                "last sync",
                "-L",
                "overleaf",
                *paths,
            ],
            cwd=tmp,
            env=git_environment(),
            capture_output=True,
        )
    # merge-file reports conflict counts from 1 to 127, capped at 127.
    if result.returncode < 0 or result.returncode > 127:
        raise SyncError(
            f"git merge-file failed (exit {result.returncode}); nothing copied. Check the installed Git and file access, then retry.",
            recovery="local-git-failure",
        )
    return result.stdout, result.returncode == 0


RECORD = "sync.json"


def record_ref(url: str) -> str:
    return f"refs/asta/overleaf/{url.rsplit('/', 1)[1]}"


def has_origin(root: Path) -> bool:
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=root,
        env=git_environment(),
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise SyncError(
            "Could not read workspace Git remotes. Check Git configuration and repository permissions, then retry.",
            recovery="local-git-failure",
        )
    return result.returncode == 0


def read_record(
    root: Path, revision: str, *, url: str | None = None, publishing: bool = False
) -> dict:
    """Validate record data before any field is used as a Git revision."""
    try:
        record = json.loads(
            git_bytes("cat-file", "blob", f"{revision}:{RECORD}", cwd=root)
        )
        if isinstance(record, dict):
            where = f"Origin's {record_ref(url)}" if url else "The sync record"
            check_format(record.get("format", 1), record.get("requires_asta"), where)
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("overleaf"), str)
            or not SHA.fullmatch(record["overleaf"])
            or not isinstance(record.get("workspace"), str)
            or not re.fullmatch(FULL_OID, record["workspace"])
            or not isinstance(record.get("url"), str)
        ):
            raise ValueError("unexpected sync record")
        record["url"] = validate_url(record["url"])
        if url is not None and record["url"] != url:
            raise ValueError("different Overleaf project")
        return record
    except (GitCommandError, KeyError, TypeError, ValueError, ProjectURLError):
        raise invalid_record(url, publishing=publishing) from None


def invalid_record(url: str | None, *, publishing: bool = False) -> SyncError:
    location = f"at origin's {record_ref(url)}" if url else "in workspace history"
    return SyncError(
        f"Invalid Overleaf sync record {location}. "
        "Restore it from its history or delete it to fall back to "
        f"{CONFIG}." + (" Nothing pushed." if publishing else " Nothing copied."),
        recovery="sync-record-ref",
    )


@contextmanager
def published_record(
    root: Path, url: str, *, publishing: bool = False, warn: bool = True
):
    """Read publish's record on `origin`: (record commit, Overleaf commit, source)."""
    ref = record_ref(url)
    suffix = " Nothing pushed." if publishing else " Nothing copied."
    unavailable = (
        "Could not read the Overleaf sync record from the workspace's `origin` remote. "
        "Check its URL, credentials and network access." + suffix
    )
    try:
        advertised = git("ls-remote", "origin", ref, cwd=root)
    except click.ClickException:
        raise OriginAccessError(unavailable, recovery="origin-cannot-be-read") from None
    if not any(line.endswith(f"\t{ref}") for line in advertised.splitlines()):
        yield None, None, None
        return
    gate = f"refs/asta/overleaf-gate/{uuid4().hex}"
    try:
        try:
            git(
                "fetch",
                "-q",
                "--no-tags",
                "--no-write-fetch-head",
                "--refmap=",
                "origin",
                f"{ref}:{gate}",
                cwd=root,
            )
        except click.ClickException:
            raise OriginAccessError(
                unavailable, recovery="origin-cannot-be-read"
            ) from None
        try:
            # The fetched object becomes commit-tree's parent; peeling a tag is unsafe.
            commit = None
            if git("cat-file", "-t", gate, cwd=root) == "commit":
                commit = git("rev-parse", gate, cwd=root)
            record = read_record(root, gate, url=url) if commit else None
        except FormatError:
            raise
        except (GitCommandError, SyncError):
            record = None
        if commit is None and publishing:
            # A fast-forward push cannot replace a non-commit; deleting the ref can.
            raise invalid_record(url, publishing=True)
        # Keep the parent reachable until a subsequent record has been pushed.
        if record is None:
            if warn:
                record_not_used("it is damaged")
            yield commit, None, None
        else:
            yield commit, record["overleaf"], record["workspace"]
    finally:
        try:
            git("update-ref", "-d", gate, cwd=root)
        except click.ClickException:
            click.echo("Could not remove the temporary Overleaf record ref.", err=True)


def record_not_used(reason: str) -> None:
    """Explain fallback and let the sync command retain the same notice."""
    message = (
        f"Overleaf sync record not used: {reason}. Pull started from "
        f"{CONFIG}'s base ({RECOVERY}#record-not-used)."
    )
    click.echo(message, err=True)
    ctx = click.get_current_context(silent=True)
    if ctx is not None and "overleaf_record_notices" in ctx.meta:
        ctx.meta["overleaf_record_notices"].append(message)


def paper_files(repo: Path, revision: str, prefix: str = "") -> dict[str, bytes]:
    # Bytes, not blob IDs: Overleaf and the workspace may use different hash functions.
    files = read_plain_files(repo, revision, prefix)
    files.pop(CONFIG, None)
    return files


def refuse_incomplete_record_history(root: Path, *, publishing: bool = False) -> None:
    """A shallow non-ancestor result cannot justify falling back to an older base."""
    if git("rev-parse", "--is-shallow-repository", cwd=root) == "true":
        raise SyncError(
            "Could not verify the Overleaf sync record against shallow workspace history. "
            "Fetch the workspace history from `origin` and retry; "
            + ("nothing pushed." if publishing else "nothing copied."),
            recovery="workspace-history-is-shallow",
        )


def reviewed_record(
    root: Path,
    repo: Path,
    prefix: str,
    default: str,
    recorded: str | None,
    source: str | None,
    *,
    publishing: bool = False,
) -> str | None:
    """The record's Overleaf commit when it matches reviewed workspace history."""
    if recorded is None or resolve_commit(repo, recorded) is None:
        return recorded  # last_sync reports a record missing from Overleaf history.
    reviewed = resolve_commit(root, source) is not None and is_ancestor(
        root, source, default
    )
    if not reviewed:
        # Missing objects and false ancestry can both be shallow-history gaps,
        # rather than evidence that the record names unreviewed content.
        refuse_incomplete_record_history(root, publishing=publishing)
    if reviewed and paper_files(repo, recorded) == paper_files(root, source, prefix):
        return recorded
    record_not_used("it does not match a paper on origin's default branch")
    return None


def last_sync(repo: Path, head: str, base: str, recorded: str | None, done: str) -> str:
    """The newer of the committed base and a record that counts, in Overleaf history."""
    counted = (
        recorded is not None
        and resolve_commit(repo, recorded) is not None
        and is_ancestor(repo, recorded, head)
    )
    if resolve_commit(repo, base) is None or not is_ancestor(repo, base, head):
        if counted:
            click.echo(
                f"{CONFIG}'s base is not in Overleaf history; starting from the "
                "published sync record instead.",
                err=True,
            )
            return recorded
        raise SyncError(
            f"{CONFIG}'s base is not in Overleaf history and no sync record counts; "
            f"{done} Set base, in a PR, to an Overleaf commit the default branch "
            f"already has ({RECOVERY}#base-not-in-overleaf-history)."
        )
    if recorded is None or recorded == base:
        return base
    if not counted:
        record_not_used("its Overleaf commit is not in Overleaf history")
        return base
    return recorded if is_ancestor(repo, base, recorded) else base


def confirm_publication(repo: Path, pushed: str, synced: str) -> str:
    """Overleaf's commit for this push; Git integration may translate pushed commits."""
    try:
        with credentials() as (env, options):
            git(
                *options,
                "fetch",
                "-q",
                "--no-tags",
                "origin",
                "HEAD",
                cwd=repo,
                env=env,
            )
        head = git("rev-parse", "FETCH_HEAD", cwd=repo)
        if is_ancestor(repo, synced, head):
            if is_ancestor(repo, pushed, head):
                # A collaborator may have edited after our push. Record only our
                # published commit so that their later edits still need review.
                return pushed
            if tree(repo, head) == tree(repo, pushed):
                return head
    except click.ClickException:
        pass
    raise SyncError(
        f"Published Overleaf commit {pushed[:7]}, but could not confirm Overleaf's copy "
        "to record the sync point. Before publishing again, run `asta workspace "
        "overleaf pull` and merge the resulting PR (it may change only paper/overleaf.json). "
        "If Overleaf history was reset, repair base using the recovery steps.",
        recovery="incomplete-publication",
    )


def record_publication(
    root: Path,
    url: str,
    previous: str | None,
    overleaf: str,
    workspace: str,
    identity: list[str],
) -> None:
    ref = record_ref(url)
    data = json.dumps(
        {**format_stamp(), "url": url, "overleaf": overleaf, "workspace": workspace},
        indent=2,
    )
    try:
        blob = git(
            "hash-object", "-w", "--stdin", cwd=root, input=(data + "\n").encode()
        )
        listing = f"100644 blob {blob}\t{RECORD}\n".encode()
        record_tree = git("mktree", cwd=root, input=listing)
        commit = git(
            *identity,
            "commit-tree",
            "--no-gpg-sign",
            *(["-p", previous] if previous else []),
            "-m",
            f"Record Overleaf commit {overleaf}",
            record_tree,
            cwd=root,
        )
        # Fast-forward only: a concurrent publisher's record is never overwritten.
        # Branch pre-push hooks do not apply to this metadata ref.
        git("push", "--quiet", "--no-verify", "origin", f"{commit}:{ref}", cwd=root)
    except click.ClickException:
        raise SyncError(
            f"Published Overleaf commit {overleaf[:7]}, but could not record it at "
            f"origin's {ref}. Before publishing again, run `asta workspace overleaf "
            "pull` and merge the resulting PR (it may change only paper/overleaf.json).",
            recovery="incomplete-publication",
        ) from None


project_option = click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
dir_option = click.option("--dir", "directory", default="paper", show_default=True)


@click.group()
def overleaf() -> None:
    """Pull an Overleaf paper into the workspace for review, then publish it back."""


@overleaf.command()
@click.argument("url", required=False)
@dir_option
@project_option
def pull(url: str | None, directory: str, project: Path) -> None:
    """Copy the Overleaf project into the paper directory and record its commit."""
    root, paper, prefix = resolve(project, directory)
    config = load_config(paper)
    url = validate_url(url or config.get("url"))
    if config and url != config["url"]:
        raise SyncError(
            "This paper is linked to another Overleaf project. "
            "Import the new project into a separate directory with --dir; nothing copied.",
            recovery="paper-directory",
        )
    require_clean(root, paper)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(url, repo)
        new = read_plain_files(repo, head)
        if CONFIG in new:
            refuse(CONFIG, "is reserved for workspace sync metadata")
        check_paths([CONFIG, *new])
        check_ignore_files(new)
        committed = read_plain_files(root, "HEAD", prefix)
        ours = committed.copy()
        ours.pop(CONFIG, None)
        base = {}
        if config:
            recorded = None
            if has_origin(root):
                with published_record(root, url) as (_, recorded, source):
                    if recorded is not None:
                        with default_branch(root) as (default, _):
                            recorded = reviewed_record(
                                root, repo, prefix, default, recorded, source
                            )
                    if (
                        recorded is not None
                        and resolve_commit(repo, recorded) is not None
                        and not (
                            resolve_commit(root, source) is not None
                            and is_ancestor(root, source, "HEAD")
                        )
                        and read_plain_files(repo, recorded) != ours
                    ):
                        # Verification against origin does not prove this checkout
                        # predates the publication when its ancestry is shallow.
                        refuse_incomplete_record_history(root)
                        # Older checkouts import the published edits for review.
                        # A shallow clone can hide ancestry; matching paper bytes
                        # above still allow it to use the published sync point.
                        click.echo(
                            "This checkout predates the last publication; "
                            f"merging from {CONFIG} instead.",
                            err=True,
                        )
                        recorded = None
            else:
                click.echo(
                    f"No `origin` remote; using {CONFIG} as the last sync. "
                    "Edits published from another clone may need conflict resolution.",
                    err=True,
                )
            base = read_plain_files(
                repo, last_sync(repo, head, config["base"], recorded, "nothing copied.")
            )
        base.pop(CONFIG, None)
        deleted = (base.keys() - new.keys()) & ours.keys()
        check_paths([CONFIG, *new, *(ours.keys() - new.keys() - deleted)])
        conflicted = []
        for name in base.keys() | new.keys():
            if new.get(name) == base.get(name):
                # Keep workspace edits when Overleaf did not change this file.
                new.pop(name, None)
            elif ours.get(name) not in (base.get(name), new.get(name)):
                if name not in new or name not in ours:
                    raise SyncError(
                        f"Workspace and Overleaf disagree on whether {name} exists. "
                        "Reconcile it first; nothing copied.",
                        recovery="file-existence-conflict",
                    )
                if name not in base:
                    # No common ancestor (e.g. an initial import over existing source).
                    raise SyncError(
                        f"{name} was added independently on both sides. Reconcile it first; nothing copied.",
                        recovery="independent-additions",
                    )
                merged, clean = merge_text(name, ours[name], base[name], new[name])
                if merged is None:
                    raise SyncError(
                        f"Both workspace and Overleaf changed {name}, which is not text "
                        "that can be merged line by line. Reconcile it first; nothing copied.",
                        recovery="concurrent-asset-edits",
                    )
                new[name] = merged
                if not clean:
                    conflicted.append(name)
        for name in new.keys() | deleted:
            target = paper / name
            if target.resolve() != target:
                refuse(name, "passes through a symlink")
        # Git's index flags can hide edits from status; verify bytes we will replace.
        for name in (new.keys() | deleted | {CONFIG}) & committed.keys():
            target = paper / name
            if not target.is_file() or target.read_bytes() != committed[name]:
                raise SyncError(
                    f"Commit or discard local changes in {target.relative_to(root)} first; nothing copied.",
                    recovery="local-changes",
                )
        for name in new:
            if (paper / name).is_dir():
                raise SyncError(
                    f"Overleaf now has a file where {(paper / name).relative_to(root)} "
                    "is a directory. Move the directory aside before pulling; nothing copied.",
                    recovery="path-collision",
                )
        for name in new.keys() | {CONFIG}:
            if name not in committed and (paper / name).exists():
                raise SyncError(
                    f"Commit or discard local changes in {(paper / name).relative_to(root)} "
                    "first; nothing copied.",
                    recovery="local-changes",
                )
        require_visible(root, [paper / name for name in (*new, CONFIG)])
        for name in (*new, CONFIG):
            for parent in (paper / name).parents:
                if parent == root:
                    break
                if parent.exists() and not parent.is_dir():
                    if parent not in {paper / item for item in deleted}:
                        raise SyncError(
                            f"{parent.relative_to(root)} is a file needed as a directory. "
                            "Move it aside before pulling; nothing copied.",
                            recovery="path-collision",
                        )
        for name in deleted:
            (paper / name).unlink(missing_ok=True)
        write_files(new, paper)
        save_config(paper, url, head)
    ctx = click.get_current_context(silent=True)
    # The sync command reports its own outcome and opens the PR itself.
    if ctx is None or not ctx.meta.get("overleaf_sync"):
        click.echo(
            f"Copied Overleaf commit {head[:7]} into {paper.relative_to(root)}/. "
            + (
                "Resolve conflicts, review with `git diff`, then commit and open a PR."
                if conflicted
                else "Review with `git diff`, then commit and open a PR."
            )
        )
    if conflicted:
        click.echo(
            "Both sides changed the same lines in: "
            + ", ".join(sorted(conflicted))
            + ". Resolve the conflict markers in the PR; publish refuses files that still have them.",
            err=True,
        )
        sys.exit(CONFLICT_EXIT)


def default_branch_ref(root: Path) -> str:
    symref = git("ls-remote", "--symref", "origin", "HEAD", cwd=root)
    match = re.search(r"^ref: refs/heads/(\S+)\tHEAD$", symref, re.M)
    if not match:
        raise SyncError(
            "Could not determine origin's default branch. Ask a repository maintainer to set an existing default branch, then retry.",
            recovery="origin-cannot-be-read",
        )
    return f"refs/heads/{match.group(1)}"


def require_expected_tip(root: Path, expected: str, ref: str | None) -> None:
    try:
        advertised = git("ls-remote", "--symref", "origin", "HEAD", cwd=root)
    except click.ClickException:
        raise SyncError(
            "Could not verify origin's default branch immediately before publication; "
            "nothing pushed. Check origin access and retry.",
            recovery="origin-cannot-be-read",
        ) from None
    branch = re.search(r"^ref: (refs/heads/\S+)\tHEAD$", advertised, re.M)
    tip = re.search(rf"^({FULL_OID})\tHEAD$", advertised, re.M)
    if not branch or not tip or branch.group(1) != ref or tip.group(1) != expected:
        raise SyncError(
            "Origin's default branch changed since the expected commit; nothing pushed. "
            "Retry after checks pass on the new tip.",
            recovery="default-branch-changed",
        )


@contextmanager
def default_branch(root: Path, *, publishing: bool = False):
    """Fetch the reviewed history without changing workspace branch refs or FETCH_HEAD."""
    gate = f"refs/asta/overleaf-gate/{uuid4().hex}"
    try:
        try:
            ref = default_branch_ref(root)
            git(
                "fetch",
                "-q",
                "--no-tags",
                "--no-write-fetch-head",
                "--refmap=",
                "origin",
                f"{ref}:{gate}",
                cwd=root,
            )
        except click.ClickException:
            raise OriginAccessError(
                "Could not fetch the default branch of the workspace's `origin` remote. "
                "Check its URL, credentials and network access."
                + (" Nothing pushed." if publishing else " Nothing copied."),
                recovery="origin-cannot-be-read",
            ) from None
        yield git("rev-parse", gate, cwd=root), ref
    finally:
        try:
            git("update-ref", "-d", gate, cwd=root)
        except click.ClickException:
            click.echo("Could not remove the temporary Overleaf review ref.", err=True)


@overleaf.command()
@dir_option
@project_option
@click.option("--dry-run", is_flag=True, help="Show what would change; push nothing.")
@click.option(
    "--expected-commit",
    help="Require this full workspace commit to remain the default-branch tip.",
)
def publish(
    directory: str, project: Path, dry_run: bool, expected_commit: str | None
) -> None:
    """Push the committed paper directory to Overleaf without rewriting its layout."""
    root, paper, prefix = resolve(project, directory)
    if expected_commit is not None:
        expected_commit = expected_commit.lower()
        if not re.fullmatch(FULL_OID, expected_commit):
            raise click.BadParameter(
                "needs a full commit id", param_hint="--expected-commit"
            )
        if git("rev-parse", "HEAD", cwd=root) != expected_commit:
            raise SyncError(
                "Check out the expected workspace commit; nothing pushed.",
                recovery="default-branch-changed",
            )
    require_visible(root, [paper / CONFIG])
    config = load_config(paper)
    if not config:
        raise SyncError(
            f"No {CONFIG}; run `asta workspace overleaf pull <url>` first.",
            recovery="paper-configuration",
        )
    require_clean(root, paper)
    ours = read_plain_files(root, "HEAD", prefix)
    if CONFIG not in ours:
        raise SyncError(
            f"Commit {(paper / CONFIG).relative_to(root)} before publishing. "
            "The sync record must belong to the committed paper revision.",
            recovery="paper-configuration",
        )
    if ours[CONFIG] != (paper / CONFIG).read_bytes():
        raise SyncError(
            f"Commit or restore {(paper / CONFIG).relative_to(root)} before publishing. "
            "The sync record differs from the committed revision.",
            recovery="paper-configuration",
        )
    # Index flags can hide edits or deletions from git status.
    for name, data in ours.items():
        target = paper / name
        if (
            target.resolve() != target
            or not target.is_file()
            or target.read_bytes() != data
        ):
            raise SyncError(
                f"Commit or discard local changes to {target.relative_to(root)} first; "
                "nothing pushed.",
                recovery="local-changes",
            )
    ours.pop(CONFIG, None)
    if not ours:
        raise SyncError(
            "Refusing to publish an empty paper; nothing pushed. Commit a paper source or correct --dir, then retry.",
            recovery="empty-paper",
        )
    check_ignore_files(ours)
    unmerged = (
        "The paper differs from the latest commit on origin's default branch. Merge "
        "changes through a reviewed PR, update your checkout to that commit, then publish"
    )
    with default_branch(root, publishing=True) as (default, reviewed_ref):
        if expected_commit is not None and default != expected_commit:
            raise SyncError(
                "Origin's default branch changed since the expected commit; nothing pushed. "
                "Retry after checks pass on the new tip.",
                recovery="default-branch-changed",
            )
        # Comparing the tip prevents republishing content a later reviewed edit removed.
        reviewed = (
            default
            if tree(root, default, prefix) == tree(root, "HEAD", prefix)
            else None
        )
        if not reviewed:
            if not dry_run:
                raise SyncError(
                    f"{unmerged}; nothing pushed.",
                    recovery="paper-not-on-default-branch",
                )
            click.echo(f"{unmerged}; publish will refuse until then.")
        with (
            published_record(root, config["url"], publishing=True) as (
                previous,
                recorded,
                source,
            ),
            tempfile.TemporaryDirectory() as tmp,
        ):
            repo = Path(tmp) / "overleaf"
            head = clone(config["url"], repo)
            recorded = reviewed_record(
                root,
                repo,
                prefix,
                default,
                recorded,
                source,
                publishing=True,
            )
            synced = last_sync(repo, head, config["base"], recorded, "nothing pushed.")
            if synced != head:
                raise SyncError(
                    "Overleaf has changed since the last sync. Run "
                    "`asta workspace overleaf pull`, review those edits in a PR, then publish; "
                    "nothing pushed.",
                    recovery="overleaf-edits-need-review",
                )
            marked = sorted(
                name
                for name, data in ours.items()
                if Path(name).suffix.lower() in MERGE_SUFFIXES
                and b"\0" not in data
                and MARKER.search(data)
            )
            if marked:
                raise SyncError(
                    "Unresolved conflict markers in: "
                    + ", ".join(marked)
                    + "; nothing pushed. Resolve the markers and commit the paper before retrying.",
                    recovery="conflict-markers-after-pull-exit-3",
                )
            write_files(ours, repo)
            git("add", "-A", "-f", cwd=repo)
            if read_plain_files(repo, git("write-tree", cwd=repo)) != ours:
                raise SyncError(
                    "Git conversions changed the exported files; nothing pushed. "
                    "Remove content-changing Git filters and conversions, or sync the paper by hand.",
                    recovery="plain-files-only",
                )
            changes = git("status", "--short", cwd=repo)
            if not changes:
                click.echo("Overleaf already matches the committed paper.")
                return
            click.echo(changes)
            identity_result = subprocess.run(
                ["git", "var", "GIT_COMMITTER_IDENT"],
                cwd=root,
                env=git_environment(),
                capture_output=True,
            )
            if identity_result.returncode:
                raise SyncError(
                    "Configure Git user.name and user.email in the workspace before publishing.",
                    recovery="git-identity",
                )
            try:
                ident = os.fsdecode(identity_result.stdout).rsplit(" ", 2)[0]
                name, email = ident.rsplit(" <", 1)
                email = email.removesuffix(">")
            except ValueError:
                raise SyncError(
                    "Could not read the workspace's Git identity; check user.name and user.email.",
                    recovery="git-identity",
                ) from None
            if dry_run:
                click.echo(
                    "Dry run: nothing pushed; commit hooks and signing were not run."
                )
                return
            identity = ["-c", f"user.name={name}", "-c", f"user.email={email}"]
            # Informational; later syncs read the sync point from the workspace record.
            message = publish_message(reviewed)
            git(
                *identity,
                *commit_settings(root),
                "commit",
                "-q",
                "-m",
                message,
                cwd=repo,
            )
            if read_plain_files(repo, "HEAD") != ours:
                raise SyncError(
                    "Git configuration or hooks changed the exported files; nothing pushed. "
                    "Remove content-changing Git filters and conversions, or sync the paper by hand.",
                    recovery="plain-files-only",
                )
            push(repo, root, expected_commit=expected_commit, reviewed_ref=reviewed_ref)
            published = confirm_publication(
                repo, git("rev-parse", "HEAD", cwd=repo), synced
            )
            record_publication(
                root, config["url"], previous, published, reviewed, identity
            )
    click.echo(f"Published Overleaf commit {published[:7]}; nothing to commit.")


@overleaf.command(name="sync")
@dir_option
@project_option
def sync(directory: str, project: Path) -> None:
    """Pull through one GitHub PR, squash a quiet checked PR, then publish."""
    from .overleaf_sync import sync_workspace

    sync_workspace(project, directory)
