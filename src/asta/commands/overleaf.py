"""Copy a paper between the workspace and Overleaf's Git bridge."""

import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

import click

CONFIG = "overleaf.json"
SHA = re.compile(r"[0-9a-f]{40}")
WINDOWS_DEVICE = re.compile(
    r"(?:con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?",
    re.IGNORECASE,
)
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
    env.update(LC_ALL="C", LANGUAGE="")
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
        if operation in ("clone", "push") and (
            re.search(rb"(?:http(?:/[\d.]+)?\s+|returned error:\s*)401\b", stderr)
            or b"authentication failed" in stderr
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
        if operation in ("clone", "push") and (
            b"rejected" in stderr or b"fetch first" in stderr
        ):
            raise click.ClickException(
                f"git {operation} was rejected. Check access and the remote state."
            )
        raise click.ClickException(
            f"git {operation} failed (exit {result.returncode})."
        )
    return result.stdout


def git(*args: str, **kwargs) -> str:
    return os.fsdecode(git_bytes(*args, **kwargs)).rstrip("\n")


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
    if os.name == "nt":
        raise click.ClickException(
            "OVERLEAF_TOKEN askpass is unavailable on Windows. Unset OVERLEAF_TOKEN "
            "and use Git's credential helper with username git and your Overleaf token."
        )
    with tempfile.TemporaryDirectory() as tmp:
        askpass = Path(tmp) / "askpass"
        askpass.write_text(
            '#!/bin/sh\ncase "$1" in Username*) echo git;; *) printf \'%s\\n\' "$OVERLEAF_TOKEN";; esac\n'
        )
        askpass.chmod(stat.S_IRWXU)
        env.update(
            OVERLEAF_TOKEN=token, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT="0"
        )
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
            url,
            str(dest),
            cwd=dest.parent,
            env=env,
        )
    return git("rev-parse", "HEAD", cwd=dest)


def push(repo: Path) -> None:
    with credentials() as (env, options):
        git(*options, "push", "--quiet", "origin", "HEAD", cwd=repo, env=env)


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


def check_paths(names) -> None:
    seen = {}
    names = set(names)
    for name in names:
        parts = name.split("/")
        if (
            any(part in ("", ".", "..") or part.casefold() == ".git" for part in parts)
            or any(
                part.endswith((".", " ")) or WINDOWS_DEVICE.fullmatch(part)
                for part in parts
            )
            or any(
                c in '\\:<>"|?*' or ord(c) < 32 or 127 <= ord(c) <= 159 for c in name
            )
        ):
            refuse(name, "has an unsafe path")
        for end in range(1, len(parts) + 1):
            prefix = "/".join(parts[:end])
            other = seen.setdefault(prefix.casefold(), prefix)
            if other != prefix:
                refuse(name, f"differs from {other} only in letter case")
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
        if name.rsplit("/", 1)[-1] == ".gitattributes":
            refuse(name, "can change file contents in transit")
        data = git_bytes("cat-file", "blob", blob, cwd=repo)
        if data.startswith(b"version https://git-lfs.github.com/spec/"):
            refuse(name, "is a Git LFS pointer")
        result[name] = data
    return result


def check_ignore_files(names) -> None:
    for name in names:
        if name.rsplit("/", 1)[-1] == ".gitignore":
            refuse(
                name,
                "can hide imported sources; keep ignore rules in the workspace root",
            )


def resolve(project: Path, directory: str) -> tuple[Path, Path, str]:
    root = Path(git("rev-parse", "--show-toplevel", cwd=project)).resolve()
    try:
        git("rev-parse", "--verify", "-q", "HEAD", cwd=root)
    except click.ClickException:
        raise click.ClickException(
            "Commit the workspace's initial files before syncing with Overleaf."
        ) from None
    paper = (root / directory).resolve()
    if root not in paper.parents:
        raise click.ClickException("--dir must be a subdirectory of the workspace.")
    return root, paper, paper.relative_to(root).as_posix() + "/"


def require_clean(root: Path, *paths: Path) -> None:
    if git(
        "--literal-pathspecs", "status", "--porcelain", "--", *map(str, paths), cwd=root
    ):
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


def require_plain_attributes(root: Path, paths) -> None:
    names = b"\0".join(os.fsencode(path.relative_to(root)) for path in paths) + b"\0"
    # An unstaged attribute edit must not hide conversions still in the index.
    for options in ([], ["--cached"]):
        result = subprocess.run(
            [
                "git",
                "check-attr",
                *options,
                "-z",
                "--stdin",
                "text",
                "eol",
                "filter",
                "crlf",
                "working-tree-encoding",
            ],
            input=names,
            cwd=root,
            env=git_environment(),
            capture_output=True,
        )
        if result.returncode:
            raise click.ClickException(
                "Could not check Git attributes; nothing copied or pushed."
            )
        fields = result.stdout.split(b"\0")[:-1]
        for name, attribute, value in zip(fields[::3], fields[1::3], fields[2::3]):
            if value not in (b"unspecified", b"unset"):
                raise click.ClickException(
                    f"{os.fsdecode(name)} has content-changing Git attribute "
                    f"{os.fsdecode(attribute)}={os.fsdecode(value)}. Remove that rule "
                    "for this paper before syncing; nothing copied or pushed."
                )


def require_unchanged_bytes(
    root: Path, paper: Path, contents: dict[str, bytes]
) -> None:
    for name, data in contents.items():
        if b"\r" not in data:
            continue
        raw = git_bytes("hash-object", "--stdin", "--no-filters", cwd=root, input=data)
        converted = git_bytes(
            "hash-object", "--stdin", "--path", str(paper / name), cwd=root, input=data
        )
        if raw != converted:
            raise click.ClickException(
                f"Git line-ending conversion would change {name!r} on commit. "
                "Disable conversion for this paper (for example, a workspace-root "
                "attribute rule with -text); nothing copied."
            )


def load_config(paper: Path) -> dict:
    path = paper / CONFIG
    if path.is_symlink():
        refuse(CONFIG, "is a symlink")
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text())
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
    (paper / CONFIG).write_text(text)


def write_files(contents: dict[str, bytes], dest: Path) -> None:
    for name, data in contents.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


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
            except click.ClickException:
                raise click.ClickException(
                    "The recorded Overleaf commit is unavailable. Reset remote history "
                    "is unsupported; import into a separate directory with --dir."
                ) from None
        base = read_plain_files(repo, config["base"]) if config else {}
        base.pop(CONFIG, None)
        committed = read_plain_files(root, "HEAD", prefix)
        ours = committed.copy()
        ours.pop(CONFIG, None)
        deleted = (base.keys() - new.keys()) & ours.keys()
        check_paths([*new, *(ours.keys() - new.keys() - deleted)])
        for name in base.keys() | new.keys():
            if new.get(name) == base.get(name):
                # Keep workspace edits when Overleaf did not change this file.
                new.pop(name, None)
            elif ours.get(name) not in (base.get(name), new.get(name)):
                raise click.ClickException(
                    f"Both workspace and Overleaf changed {name}. Reconcile it first; nothing copied."
                )
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
        replaced_dirs = [paper / name for name in new if (paper / name).is_dir()]
        for target in replaced_dirs:
            for child in target.rglob("*"):
                if child.is_symlink() or (
                    not child.is_dir()
                    and child.relative_to(paper).as_posix() not in deleted
                ):
                    raise click.ClickException(
                        f"Directory {target.relative_to(root)} contains workspace files; "
                        "move them aside before replacing it; nothing copied."
                    )
        require_visible(root, [paper / name for name in (*new, CONFIG)])
        require_plain_attributes(root, [paper / name for name in (*new, CONFIG)])
        require_unchanged_bytes(root, paper, new)
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
        try:
            for name in deleted:
                (paper / name).unlink(missing_ok=True)
            for target in replaced_dirs:
                for child in sorted(
                    target.rglob("*"), key=lambda p: len(p.parts), reverse=True
                ):
                    child.rmdir()
                target.rmdir()
            write_files(new, paper)
            save_config(paper, url, head)
        except OSError:
            raise click.ClickException(
                "Could not write the imported paper. Check permissions and free disk space, "
                "then inspect `git diff` and `git status`. Pull may be partially applied. "
                "Back up the paper directory before recovery: restore affected tracked "
                "files with `git restore --source=HEAD -- <paths>` and remove only "
                "newly imported files before retrying."
            ) from None
    click.echo(
        f"Copied Overleaf commit {head[:7]} into {paper.relative_to(root)}/. "
        "Review with `git diff`, then commit and open a PR."
    )


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
    ours.pop(CONFIG, None)
    check_ignore_files(ours)
    require_plain_attributes(root, [paper / name for name in (*ours, CONFIG)])
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(config["url"], repo)
        if head != config["base"]:
            raise click.ClickException(
                f"Overleaf has changed since commit {config['base'][:7]}. Run "
                "`asta workspace overleaf pull`, review those edits in a PR, then publish."
            )
        git("rm", "-r", "-q", "--ignore-unmatch", ".", cwd=repo)
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
        message = f"Publish workspace commit {git('rev-parse', 'HEAD', cwd=root)[:12]}"
        git(*identity, "commit", "-q", "-m", message, cwd=repo)
        if read_plain_files(repo, "HEAD") != ours:
            raise click.ClickException(
                "Git configuration or hooks changed the exported files; nothing pushed. "
                "Content-changing Git filters and conversions are unsupported."
            )
        push(repo)
        published = git("rev-parse", "HEAD", cwd=repo)
    save_config(paper, config["url"], published)
    click.echo(
        f"Published Overleaf commit {published[:7]}. Commit "
        f"{(paper / CONFIG).relative_to(root)} so the next publish starts from it."
    )
