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
BIBLIOGRAPHY = "references.bib"
SHA = re.compile(r"[0-9a-f]{40}")


def git_environment() -> dict:
    # Hooks export repository routing; tracing can log authorization headers.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")
        and not key.startswith("GIT_TRACE")
        and key != "GIT_CURL_VERBOSE"
    }
    env.update(LC_ALL="C", LANGUAGE="")
    return env


def git_bytes(*args: str, cwd: Path, env: dict | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=git_environment() if env is None else env,
        capture_output=True,
    )
    if result.returncode:
        # Diagnostics may contain URLs or credential-helper output, so never echo them.
        stderr = result.stderr.lower()
        if b"401" in stderr or b"authentication failed" in stderr:
            raise click.ClickException(
                "Overleaf authentication failed. Check OVERLEAF_TOKEN or your Git credential helper."
            )
        if b"403" in stderr:
            raise click.ClickException(
                "Overleaf access denied. Check your token and access to this project."
            )
        if b"rejected" in stderr or b"fetch first" in stderr:
            raise click.ClickException(
                "Overleaf changed during publish. Pull and review the changes first."
            )
        raise click.ClickException(f"git {args[0]} failed (exit {result.returncode}).")
    return result.stdout


def git(*args: str, **kwargs) -> str:
    return os.fsdecode(git_bytes(*args, **kwargs)).strip()


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
    if not env.get("OVERLEAF_TOKEN"):
        yield env, []
        return
    with tempfile.TemporaryDirectory() as tmp:
        askpass = Path(tmp) / "askpass"
        askpass.write_text(
            '#!/bin/sh\ncase "$1" in Username*) echo git;; *) printf \'%s\\n\' "$OVERLEAF_TOKEN";; esac\n'
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
    out = git_bytes("ls-tree", "-r", "-z", revision, "--", prefix or ".", cwd=repo)
    result = {}
    for entry in filter(None, out.split(b"\0")):
        meta, path = entry.split(b"\t", 1)
        mode, _, blob = meta.decode().split()
        result[os.fsdecode(path)[len(prefix) :]] = (mode, blob)
    return result


def refuse(name: str, reason: str) -> None:
    raise click.ClickException(
        f"Overleaf sync copies plain files only: {name} {reason}. "
        "Remove it or sync this paper by hand."
    )


def check_paths(names) -> None:
    seen = {}
    names = set(names)
    for name in names:
        parts = name.split("/")
        if (
            any(part in ("", ".", "..") or part.casefold() == ".git" for part in parts)
            or "\\" in name
            or ":" in name
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
        if prefix and name == BIBLIOGRAPHY:
            refuse(
                prefix + name,
                "duplicates the canonical root bibliography; move its entries there and commit",
            )
        if mode != "100644":
            refuse(name, "is executable, a symlink or a submodule")
        if name.rsplit("/", 1)[-1] == ".gitattributes":
            refuse(name, "can change file contents in transit")
        data = git_bytes("cat-file", "blob", blob, cwd=repo)
        if data.startswith(b"version https://git-lfs.github.com/spec/"):
            refuse(name, "is a Git LFS pointer")
        result[name] = data
    return result


def resolve(project: Path, directory: str) -> tuple[Path, Path, str]:
    root = Path(git("rev-parse", "--show-toplevel", cwd=project)).resolve()
    paper = (root / directory).resolve()
    if root not in paper.parents:
        raise click.ClickException("--dir must be a subdirectory of the workspace.")
    return root, paper, paper.relative_to(root).as_posix() + "/"


def require_clean(root: Path, *paths: Path) -> None:
    if git("status", "--porcelain", "--", *map(str, paths), cwd=root):
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
    config = json.loads(path.read_text())
    if not SHA.fullmatch(str(config.get("base", ""))):
        raise click.ClickException(f"{CONFIG} has no valid base commit.")
    config["url"] = validate_url(config.get("url"))
    return config


def save_config(paper: Path, url: str, base: str) -> None:
    text = json.dumps({"url": url, "base": base}, indent=2) + "\n"
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
    require_clean(root, paper)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(url, repo)
        new = read_plain_files(repo, head)
        if CONFIG in new:
            refuse(CONFIG, "is reserved for workspace sync metadata")
        for name in new:
            if name.rsplit("/", 1)[-1] == ".gitignore":
                refuse(
                    name,
                    "can hide imported sources; keep ignore rules in the workspace root",
                )
        overleaf_bib = new.pop(BIBLIOGRAPHY, None)
        base = read_plain_files(repo, config["base"]) if config else {}
        base.pop(BIBLIOGRAPHY, None)
        base.pop(CONFIG, None)
        ours = read_plain_files(root, "HEAD", prefix)
        ours.pop(CONFIG, None)
        check_paths([*new, *(ours.keys() - new.keys())])
        imported_paths = [paper / name for name in (*new, CONFIG)]
        deleted = base.keys() - new.keys()
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
        require_visible(root, imported_paths)
        for name in deleted:
            (paper / name).unlink(missing_ok=True)
        write_files(new, paper)
    save_config(paper, url, head)
    root_bib = root / BIBLIOGRAPHY
    if overleaf_bib and (
        not root_bib.exists() or root_bib.read_bytes() != overleaf_bib
    ):
        click.echo(
            f"Overleaf's {BIBLIOGRAPHY} differs from the workspace root copy and was not "
            "imported; move any entries you need into the root file.",
            err=True,
        )
    click.echo(
        f"Copied Overleaf commit {head[:7]} into {paper.relative_to(root)}/. "
        "Review with `git diff`, then commit and open a PR."
    )


@overleaf.command()
@dir_option
@project_option
@click.option("--dry-run", is_flag=True, help="Show what would change; push nothing.")
@click.option(
    "--replace-bibliography",
    is_flag=True,
    help="Confirm the reviewed root bibliography should replace Overleaf's differing copy.",
)
def publish(
    directory: str, project: Path, dry_run: bool, replace_bibliography: bool
) -> None:
    """Push the committed paper and root references.bib to Overleaf."""
    root, paper, prefix = resolve(project, directory)
    config = load_config(paper)
    if not config:
        raise click.ClickException(
            f"No {CONFIG}; run `asta workspace overleaf pull <url>` first."
        )
    root_bib = root / BIBLIOGRAPHY
    require_clean(root, paper, root_bib)
    ours = read_plain_files(root, "HEAD", prefix)
    ours.pop(CONFIG, None)
    bibliography = tree(root, "HEAD").get(BIBLIOGRAPHY)
    if not bibliography:
        raise click.ClickException(f"Commit the canonical root {BIBLIOGRAPHY} first.")
    mode, blob = bibliography
    if mode != "100644":
        refuse(BIBLIOGRAPHY, "is not a regular non-executable file")
    data = git_bytes("cat-file", "blob", blob, cwd=root)
    if data.startswith(b"version https://git-lfs.github.com/spec/"):
        refuse(BIBLIOGRAPHY, "is a Git LFS pointer")
    ours[BIBLIOGRAPHY] = data
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(config["url"], repo)
        if head != config["base"]:
            raise click.ClickException(
                f"Overleaf has changed since commit {config['base'][:7]}. Run "
                "`asta workspace overleaf pull`, review those edits in a PR, then publish."
            )
        remote_bib = read_plain_files(repo, head).get(BIBLIOGRAPHY)
        if remote_bib is not None and remote_bib != ours[BIBLIOGRAPHY]:
            message = (
                f"Overleaf's {BIBLIOGRAPHY} differs from the workspace root copy. "
                "Reconcile its entries in a PR first; use --replace-bibliography only "
                "to confirm the reviewed root copy should replace it."
            )
            if not dry_run and not replace_bibliography:
                raise click.ClickException(message)
            click.echo(message, err=True)
        git("rm", "-r", "-q", "--ignore-unmatch", ".", cwd=repo)
        write_files(ours, repo)
        git("add", "-A", cwd=repo)
        changes = git("status", "--short", cwd=repo)
        if not changes:
            click.echo("Overleaf already matches the committed paper.")
            return
        click.echo(changes)
        if dry_run:
            click.echo("Dry run: nothing pushed.")
            return
        identity = []
        if subprocess.run(
            ["git", "var", "GIT_COMMITTER_IDENT"],
            cwd=root,
            env=git_environment(),
            capture_output=True,
        ).returncode:
            identity = [
                "-c",
                "user.name=Asta Workspace",
                "-c",
                "user.email=asta@allenai.org",
            ]
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
