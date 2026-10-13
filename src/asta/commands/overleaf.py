"""Copy a paper between the workspace and Overleaf's Git bridge."""

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import ExitStack, contextmanager
from pathlib import Path
from uuid import uuid4

import click

CONFIG = "overleaf.json"
SHA = re.compile(r"[0-9a-f]{40}")
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
            raise click.ClickException(
                "Workspace pre-push hook failed; nothing pushed. "
                "Check the hook against the exported paper directory and Overleaf remote."
            )
        if operation in ("clone", "push") and (
            re.search(rb"(?:http(?:/[\d.]+)?\s+|returned error:\s*)401\b", stderr)
            or b"authentication failed" in stderr
            or b"could not read username" in stderr
            or b"could not read password" in stderr
        ):
            raise click.ClickException(
                "Overleaf authentication failed. Check OVERLEAF_TOKEN or your Git credential helper."
            )
        if operation in ("clone", "push") and re.search(
            rb"(?:http(?:/[\d.]+)?\s+|returned error:\s*)403\b", stderr
        ):
            raise click.ClickException(
                "Overleaf access denied. Check your token and access to this project."
            )
        if operation == "push" and (
            b"fetch first" in stderr or b"non-fast-forward" in stderr
        ):
            raise click.ClickException(
                "Overleaf changed while publishing; nothing pushed. "
                "Run `asta workspace overleaf pull`, review the changes in a PR, "
                "then publish again."
            )
        if operation == "push" and b"rejected" in stderr:
            raise click.ClickException(
                f"git {operation} was rejected. Check access and the remote state."
            )
        if operation in ("clone", "push"):
            raise click.ClickException(
                f"git {operation} failed (exit {result.returncode}). "
                "Check your Overleaf credentials, project access, network and remote state."
                + (
                    " Also check workspace pre-push hooks."
                    if operation == "push"
                    else ""
                )
            )
        if operation == "commit":
            raise click.ClickException(
                f"git commit failed (exit {result.returncode}). "
                "Check workspace commit hooks and signing settings. "
                "Hooks run in the exported paper directory, not the full workspace."
            )
        raise click.ClickException(
            f"git {operation} failed (exit {result.returncode})."
        )
    return result.stdout


def git(*args: str, **kwargs) -> str:
    return os.fsdecode(git_bytes(*args, **kwargs)).rstrip("\n")


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
            raise click.ClickException("Could not read workspace Git commit settings.")
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
        raise click.ClickException(
            "Give the project's Git URL: https://git.overleaf.com/<project-id>."
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
        raise click.ClickException("Overleaf project has no commits to sync.") from None


def push(repo: Path, root: Path) -> None:
    with credentials() as (env, options):
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
    raise click.ClickException(
        f"Overleaf sync copies plain files only: {name!r} {reason}. "
        "Remove it or sync this paper by hand."
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
            raise click.ClickException(
                f"Overleaf sync refuses {name!r}: ignore rules can hide imported sources. "
                "Keep ignore rules in the workspace root."
            )


def resolve(project: Path, directory: str) -> tuple[Path, Path, str]:
    root = Path(git("rev-parse", "--show-toplevel", cwd=project)).resolve()
    try:
        git("rev-parse", "--verify", "-q", "HEAD", cwd=root)
    except click.ClickException:
        raise click.ClickException(
            "Commit the workspace's initial files before syncing with Overleaf."
        ) from None
    if Path(directory).is_absolute():
        raise click.ClickException("--dir must be relative to the workspace.")
    candidate = root / directory
    for path in (candidate, *candidate.parents):
        if path == root:
            break
        if path.is_symlink():
            refuse(directory, "uses a symlinked directory")
    paper = candidate.resolve()
    if root not in paper.parents:
        raise click.ClickException("--dir must be a subdirectory of the workspace.")
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
        raise click.ClickException(f"Commit or discard local changes in {names} first.")


def require_visible(root: Path, paths) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-z", "--stdin"],
        input=b"\0".join(os.fsencode(path) for path in paths) + b"\0",
        cwd=root,
        env=git_environment(),
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise click.ClickException("Could not check Git ignore rules; nothing copied.")
    if result.stdout:
        name = Path(os.fsdecode(result.stdout.split(b"\0", 1)[0]))
        raise click.ClickException(
            f"{name.relative_to(root)} is ignored by Git. Adjust the ignore rules "
            "so imported sources and sync metadata can be committed; nothing copied."
        )


def load_config(paper: Path) -> dict:
    path = paper / CONFIG
    if path.is_symlink():
        refuse(CONFIG, "is a symlink")
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("base"), str):
            raise ValueError("expected an object with a base commit")
        if not SHA.fullmatch(config["base"]) or not isinstance(config.get("url"), str):
            raise ValueError("expected a base commit and project URL")
        config["url"] = validate_url(config["url"])
        return config
    except (ValueError, OSError, click.ClickException):
        raise click.ClickException(
            f"Invalid sync record: {path}. Restore its project URL and base commit from Git."
        ) from None


def save_config(paper: Path, url: str, base: str) -> None:
    text = json.dumps({"url": url, "base": base}, indent=2) + "\n"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / CONFIG).write_text(text, encoding="utf-8")


def write_files(contents: dict[str, bytes], dest: Path) -> None:
    for name, data in contents.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


MARKER = re.compile(
    rb"^(?:<<<<<<< workspace|\|{7} last sync|>>>>>>> overleaf)\r?$", re.M
)
PUBLISH_MESSAGE = re.compile(
    r"^Publish workspace commit ([0-9a-f]{7,40}|[0-9a-f]{64})$"
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
    if result.returncode < 0 or result.returncode > 127:
        raise click.ClickException(
            f"git merge-file failed (exit {result.returncode}); nothing copied."
        )
    return result.stdout, result.returncode == 0


def last_sync(
    repo: Path,
    head: str,
    base: str,
    root: Path,
    prefix: str,
    reviewed: str | None = None,
    local: dict[str, bytes] | None = None,
    dry_run: bool = False,
) -> str:
    """Newest Overleaf commit since `base` whose files match a published workspace commit.

    Publish records nothing in the workspace; its Overleaf commit names the workspace
    commit it sent, and counts as a sync point only if the content still matches it.
    """

    def warn_fallback() -> None:
        click.echo(
            "Could not verify workspace publication history from `origin`. "
            "Pulling from the recorded sync instead; published edits may "
            "need conflict resolution.",
            err=True,
        )

    try:
        git("cat-file", "-e", f"{base}^{{commit}}", cwd=repo)
        git("merge-base", "--is-ancestor", base, head, cwd=repo)
    except click.ClickException:
        raise click.ClickException(
            "Overleaf history no longer continues from the recorded commit. "
            "Reset remote history is unsupported; nothing synced. "
            "Import into a separate directory with --dir."
        ) from None
    commits = git(
        "log", "--first-parent", "--format=%H %s", f"{base}..{head}", cwd=repo
    ).splitlines()
    with ExitStack() as stack:
        for entry in commits:
            commit, _, message = entry.partition(" ")
            match = PUBLISH_MESSAGE.match(message)
            if not match:
                continue
            if reviewed is None:
                try:
                    reviewed = stack.enter_context(default_branch(root))
                except click.ClickException:
                    warn_fallback()
                    return base
            try:
                source = publication_source(
                    root, match.group(1), reviewed, dry_run=dry_run
                )
            except click.ClickException:
                if local is None:
                    raise
                warn_fallback()
                return base
            if source is None:
                continue
            published = read_plain_files(root, source, prefix)
            published.pop(CONFIG, None)
            if published == read_plain_files(repo, commit):
                if local is not None and local != published:
                    # Pull must not skip published edits absent from this checkout.
                    try:
                        git("merge-base", "--is-ancestor", source, "HEAD", cwd=root)
                    except click.ClickException:
                        try:
                            if not complete_history(root, dry_run=dry_run):
                                continue
                        except click.ClickException:
                            warn_fallback()
                            return base
                        try:
                            git("merge-base", "--is-ancestor", source, "HEAD", cwd=root)
                        except click.ClickException:
                            continue
                return commit
    return base


def complete_history(root: Path, *, dry_run: bool = False) -> bool:
    if git("rev-parse", "--is-shallow-repository", cwd=root) != "true":
        return False
    if dry_run:
        raise click.ClickException(
            "Could not verify a workspace publication from shallow history during dry-run. "
            "Fetch complete `origin` history first; dry-run leaves shallow history unchanged."
        )
    try:
        ref = default_branch_ref(root)
        git(
            "fetch",
            "-q",
            "--no-tags",
            "--no-write-fetch-head",
            "--refmap=",
            "--unshallow",
            "origin",
            ref,
            cwd=root,
        )
    except click.ClickException:
        raise click.ClickException(
            "Could not fetch complete history from the workspace's `origin` remote. "
            "Check its URL, credentials and network access."
        ) from None
    return True


def publication_source(
    root: Path, marker: str, reviewed: str, *, dry_run: bool = False
) -> str | None:
    def verify() -> str | None:
        try:
            source = git(
                "rev-parse", "--verify", "-q", f"{marker}^{{commit}}", cwd=root
            )
            git("merge-base", "--is-ancestor", source, reviewed, cwd=root)
            return source
        except click.ClickException:
            return None

    source = verify()
    if source is None and complete_history(root, dry_run=dry_run):
        # Keep the original review gate even if origin advances during this fetch.
        source = verify()
    return source


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
        raise click.ClickException(
            "This paper is linked to another Overleaf project. "
            "Import the new project into a separate directory with --dir; nothing copied."
        )
    require_clean(root, paper)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(url, repo)
        new = read_plain_files(repo, head)
        if CONFIG in new:
            refuse(CONFIG, "is reserved for workspace sync metadata")
        check_ignore_files(new)
        if config:
            try:
                git("cat-file", "-e", f"{config['base']}^{{commit}}", cwd=repo)
                git("merge-base", "--is-ancestor", config["base"], head, cwd=repo)
            except click.ClickException:
                raise click.ClickException(
                    "Overleaf history no longer continues from the recorded commit. "
                    "Reset remote history is unsupported; nothing copied. "
                    "Import into a separate directory with --dir."
                ) from None
        committed = read_plain_files(root, "HEAD", prefix)
        ours = committed.copy()
        ours.pop(CONFIG, None)
        base = (
            read_plain_files(
                repo,
                last_sync(repo, head, config["base"], root, prefix, local=ours),
            )
            if config
            else {}
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
                    raise click.ClickException(
                        f"Workspace and Overleaf disagree on whether {name} exists. "
                        "Reconcile it first; nothing copied."
                    )
                if name not in base:
                    # No common ancestor (e.g. an initial import over existing source).
                    raise click.ClickException(
                        f"Both workspace and Overleaf changed {name}. Reconcile it first; nothing copied."
                    )
                merged, clean = merge_text(name, ours[name], base[name], new[name])
                if merged is None:
                    raise click.ClickException(
                        f"Both workspace and Overleaf changed {name}, which is not text "
                        "that can be merged line by line. Reconcile it first; nothing copied."
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
                raise click.ClickException(
                    f"Commit or discard local changes in {target.relative_to(root)} first; nothing copied."
                )
        for name in new:
            if (paper / name).is_dir():
                raise click.ClickException(
                    f"Overleaf now has a file where {(paper / name).relative_to(root)} "
                    "is a directory. Move the directory aside before pulling; nothing copied."
                )
        for name in new.keys() | {CONFIG}:
            if name not in committed and (paper / name).exists():
                raise click.ClickException(
                    f"Commit or discard local changes in {(paper / name).relative_to(root)} "
                    "first; nothing copied."
                )
        require_visible(root, [paper / name for name in (*new, CONFIG)])
        for name in (*new, CONFIG):
            for parent in (paper / name).parents:
                if parent == root:
                    break
                if parent.exists() and not parent.is_dir():
                    if parent not in {paper / item for item in deleted}:
                        raise click.ClickException(
                            f"{parent.relative_to(root)} is a file needed as a directory. "
                            "Move it aside before pulling; nothing copied."
                        )
        for name in deleted:
            (paper / name).unlink(missing_ok=True)
        write_files(new, paper)
        save_config(paper, url, head)
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
        raise click.ClickException("Could not determine origin's default branch.")
    return f"refs/heads/{match.group(1)}"


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
            raise click.ClickException(
                "Could not fetch the default branch of the workspace's `origin` remote. "
                "Check its URL, credentials and network access."
                + (" Nothing pushed." if publishing else "")
            ) from None
        yield git("rev-parse", gate, cwd=root)
    finally:
        git("update-ref", "-d", gate, cwd=root)


@overleaf.command()
@dir_option
@project_option
@click.option("--dry-run", is_flag=True, help="Show what would change; push nothing.")
def publish(directory: str, project: Path, dry_run: bool) -> None:
    """Push the committed paper directory to Overleaf without rewriting its layout."""
    root, paper, prefix = resolve(project, directory)
    require_visible(root, [paper / CONFIG])
    config = load_config(paper)
    if not config:
        raise click.ClickException(
            f"No {CONFIG}; run `asta workspace overleaf pull <url>` first."
        )
    require_clean(root, paper)
    ours = read_plain_files(root, "HEAD", prefix)
    if CONFIG not in ours:
        raise click.ClickException(
            f"Commit {(paper / CONFIG).relative_to(root)} before publishing. "
            "The sync record must belong to the committed paper revision."
        )
    if ours[CONFIG] != (paper / CONFIG).read_bytes():
        raise click.ClickException(
            f"Commit or restore {(paper / CONFIG).relative_to(root)} before publishing. "
            "The sync record differs from the committed revision."
        )
    # Index flags can hide edits or deletions from git status.
    for name, data in ours.items():
        target = paper / name
        if (
            target.resolve() != target
            or not target.is_file()
            or target.read_bytes() != data
        ):
            raise click.ClickException(
                f"Commit or discard local changes to {target.relative_to(root)} first; "
                "nothing pushed."
            )
    ours.pop(CONFIG, None)
    if not ours:
        raise click.ClickException(
            "Refusing to publish an empty paper; nothing pushed."
        )
    check_ignore_files(ours)
    unmerged = (
        "The paper differs from the latest commit on origin's default branch. Merge "
        "changes through a reviewed PR, update your checkout to that commit, then publish"
    )
    with default_branch(root, publishing=True) as default:
        # Comparing the tip prevents republishing content a later reviewed edit removed.
        reviewed = (
            default
            if tree(root, default, prefix) == tree(root, "HEAD", prefix)
            else None
        )
        if not reviewed:
            if not dry_run:
                raise click.ClickException(f"{unmerged}; nothing pushed.")
            click.echo(f"{unmerged}; publish will refuse until then.")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "overleaf"
            head = clone(config["url"], repo)
            try:
                synced = last_sync(
                    repo,
                    head,
                    config["base"],
                    root,
                    prefix,
                    reviewed=default,
                    dry_run=dry_run,
                )
            except click.ClickException as exc:
                raise click.ClickException(f"{exc.message} Nothing pushed.") from None
            if synced != head:
                raise click.ClickException(
                    "Overleaf has changed since the last sync. Run "
                    "`asta workspace overleaf pull`, review those edits in a PR, then publish; "
                    "nothing pushed."
                )
            marked = sorted(
                name
                for name, data in ours.items()
                if Path(name).suffix.lower() in MERGE_SUFFIXES
                and b"\0" not in data
                and MARKER.search(data)
            )
            if marked:
                raise click.ClickException(
                    "Unresolved conflict markers in: "
                    + ", ".join(marked)
                    + "; nothing pushed."
                )
            write_files(ours, repo)
            git("add", "-A", "-f", cwd=repo)
            if read_plain_files(repo, git("write-tree", cwd=repo)) != ours:
                raise click.ClickException(
                    "Git conversions changed the exported files; nothing pushed. "
                    "Content-changing Git filters and conversions are unsupported."
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
                raise click.ClickException(
                    "Configure Git user.name and user.email in the workspace before publishing."
                )
            try:
                ident = os.fsdecode(identity_result.stdout).rsplit(" ", 2)[0]
                name, email = ident.rsplit(" <", 1)
                email = email.removesuffix(">")
            except ValueError:
                raise click.ClickException(
                    "Could not read the workspace's Git identity; check user.name and user.email."
                ) from None
            if dry_run:
                click.echo(
                    "Dry run: nothing pushed; commit hooks and signing were not run."
                )
                return
            identity = ["-c", f"user.name={name}", "-c", f"user.email={email}"]
            # Later syncs recognize this commit as a sync point by the reviewed commit it names.
            message = f"Publish workspace commit {reviewed or git('rev-parse', 'HEAD', cwd=root)}"
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
                raise click.ClickException(
                    "Git configuration or hooks changed the exported files; nothing pushed. "
                    "Content-changing Git filters and conversions are unsupported."
                )
            push(repo, root)
            published = git("rev-parse", "HEAD", cwd=repo)
    click.echo(f"Published Overleaf commit {published[:7]}; nothing to commit.")
