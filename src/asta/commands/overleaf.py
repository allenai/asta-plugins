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
# Repository-local variables reported by `git rev-parse --local-env-vars`, plus namespace.
GIT_LOCAL_ENV = {
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
    # Hooks export repository routing; tracing can log authorization headers.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in GIT_LOCAL_ENV
        and not key.startswith("GIT_TRACE")
        and key != "GIT_CURL_VERBOSE"
    }
    env.update(LC_ALL="C", LANGUAGE="", GIT_TRACE_REDACT="1")
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
        network = "clone" in args or "push" in args
        if network and (b"401" in stderr or b"authentication failed" in stderr):
            raise click.ClickException(
                "Overleaf authentication failed. Check OVERLEAF_TOKEN or your Git credential helper."
            )
        if network and b"403" in stderr:
            raise click.ClickException(
                "Overleaf access denied. Check your token and access to this project."
            )
        if "push" in args and (b"rejected" in stderr or b"fetch first" in stderr):
            raise click.ClickException(
                "Overleaf changed during publish. Pull and review the changes first."
            )
        raise click.ClickException(f"git {args[0]} failed (exit {result.returncode}).")
    return result.stdout


def git(*args: str, **kwargs) -> str:
    return os.fsdecode(git_bytes(*args, **kwargs)).strip()


def validate_url(url: str | None) -> str:
    match = re.fullmatch(
        r"https://(?:git@)?git\.overleaf\.com/([A-Za-z0-9]+)(?:\.git)?/?",
        url if isinstance(url, str) else "",
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
            url,
            str(dest),
            cwd=dest.parent,
            env=env,
        )
    return git("rev-parse", "HEAD", cwd=dest)


def push(repo: Path) -> None:
    with credentials() as (env, options):
        git(*options, "push", "--quiet", "origin", "HEAD", cwd=repo, env=env)


def files(repo: Path, revision: str, prefix: str = "") -> dict[str, tuple[str, str]]:
    """Map regular-file paths to Git mode and blob id; refuse unsupported entries."""
    out = git_bytes("ls-tree", "-r", "-z", revision, "--", prefix or ".", cwd=repo)
    result = {}
    for entry in filter(None, out.split(b"\0")):
        meta, path = entry.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        name = os.fsdecode(path)
        if any(
            part.lower() in ("..", ".git")
            for part in name.replace("\\", "/").split("/")
        ):
            raise click.ClickException(f"Cannot sync unsafe Git path: {name}.")
        if prefix.endswith("/"):
            name = name[len(prefix) :]
        if kind != "blob" or mode not in ("100644", "100755"):
            raise click.ClickException(
                f"Cannot sync {name}: only regular files are supported."
            )
        result[name] = (mode, blob)
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


def load_config(paper: Path) -> dict:
    path = paper / CONFIG
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise click.ClickException(
            f"Cannot read {CONFIG}; restore valid JSON metadata."
        ) from exc
    if not isinstance(config, dict):
        raise click.ClickException(
            f"{CONFIG} must contain a JSON object with url and base."
        )
    if not isinstance(config.get("base"), str) or not SHA.fullmatch(config["base"]):
        raise click.ClickException(f"{CONFIG} has no valid base commit.")
    config["url"] = validate_url(config.get("url"))
    return config


def save_config(paper: Path, url: str, base: str) -> None:
    text = json.dumps({"url": url, "base": base}, indent=2) + "\n"
    (paper / CONFIG).write_text(text)


def write_blob(repo: Path, entry: tuple[str, str], target: Path) -> None:
    mode, blob = entry
    target.parent.mkdir(parents=True, exist_ok=True)
    content = git_bytes("cat-file", "blob", blob, cwd=repo)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
    permissions = stat.S_IMODE(target.stat().st_mode) & ~0o111
    if mode == "100755":
        permissions |= (permissions & 0o444) >> 2
    target.chmod(permissions)


def require_visible(repo: Path, paths: list[str], *, no_index: bool = False) -> None:
    if not paths:
        return
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z", *(["--no-index"] if no_index else [])],
        cwd=repo,
        env=git_environment(),
        capture_output=True,
        input=b"\0".join(os.fsencode(name) for name in paths) + b"\0",
    )
    if result.returncode not in (0, 1):
        raise click.ClickException("Could not check paper ignore rules.")
    if result.stdout:
        raise click.ClickException(
            "Ignore rules hide imported files: "
            + ", ".join(
                os.fsdecode(name) for name in result.stdout.split(b"\0") if name
            )
            + ". Adjust the ignore rules before pulling."
        )


project_option = click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
dir_option = click.option(
    "--dir",
    "directory",
    default="paper",
    show_default=True,
    help="Paper directory relative to the workspace repository root.",
)


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
            "This paper is linked to a different Overleaf project. Use a separate --dir "
            "to import the other project."
        )
    require_clean(root, paper)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(url, repo)
        new = files(repo, head)
        overleaf_bib = new.pop(BIBLIOGRAPHY, None)
        if CONFIG in new:
            raise click.ClickException(
                f"Overleaf contains reserved workspace file {CONFIG}."
            )
        if config:
            try:
                git("cat-file", "-e", config["base"] + "^{commit}", cwd=repo)
            except click.ClickException as exc:
                raise click.ClickException(
                    "The recorded Overleaf base is missing from its history. Import into "
                    "a separate --dir and compare the copies before reconnecting."
                ) from exc
        base = files(repo, config["base"]) if config else {}
        base.pop(BIBLIOGRAPHY, None)
        base.pop(CONFIG, None)
        ours = files(root, "HEAD", prefix)
        # Keep committed workspace edits when Overleaf is unchanged; never merge silently.
        changes = {
            name for name in base.keys() | new.keys() if new.get(name) != ours.get(name)
        }
        conflicts = {
            name
            for name in changes
            if ours.get(name) != base.get(name) and new.get(name) != base.get(name)
        }
        if conflicts:
            raise click.ClickException(
                "Workspace and Overleaf both changed: "
                + ", ".join(sorted(conflicts))
                + ". Reconcile these files before pulling."
            )
        changes = {name for name in changes if new.get(name) != base.get(name)}
        destinations = [prefix + name for name in new] + [prefix + CONFIG]
        require_visible(root, destinations)
        # Incoming .gitignore files must not hide new sources after they are copied.
        require_visible(
            repo, [name for name in new if name not in ours] + [CONFIG], no_index=True
        )
        for name in changes | {CONFIG}:
            target = paper / name
            if any(path.is_symlink() for path in (target, *target.parents)):
                raise click.ClickException(
                    f"Cannot sync {name}: workspace path is a symlink."
                )
        for name in sorted(changes):
            if name in new:
                write_blob(repo, new[name], paper / name)
            else:
                (paper / name).unlink(missing_ok=True)
    save_config(paper, url, head)
    root_bib = root / BIBLIOGRAPHY
    if overleaf_bib and (
        not root_bib.exists()
        or git("hash-object", "--", str(root_bib), cwd=root) != overleaf_bib[1]
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
def publish(directory: str, project: Path, dry_run: bool) -> None:
    """Push the committed paper and root references.bib to Overleaf."""
    root, paper, prefix = resolve(project, directory)
    config = load_config(paper)
    if not config:
        raise click.ClickException(
            f"No {CONFIG}; run `asta workspace overleaf pull <url>` first."
        )
    root_bib = root / BIBLIOGRAPHY
    require_clean(root, paper, root_bib)
    ours = files(root, "HEAD", prefix)
    ours.pop(CONFIG, None)
    bibliography = files(root, "HEAD", BIBLIOGRAPHY).get(BIBLIOGRAPHY)
    if bibliography is None:
        raise click.ClickException(
            f"Commit a root {BIBLIOGRAPHY} before publishing. Overleaf's bibliography "
            "has not been changed; copy any needed entries into the root file first."
        )
    if BIBLIOGRAPHY in ours and ours[BIBLIOGRAPHY] != bibliography:
        raise click.ClickException(
            f"{prefix}{BIBLIOGRAPHY} differs from the canonical root file. Reconcile "
            "the copies before publishing; keep paper-only entries in a separate .bib file."
        )
    ours[BIBLIOGRAPHY] = bibliography
    workspace_commit = git("rev-parse", "HEAD", cwd=root)
    click.echo(
        f"Publishing workspace commit {workspace_commit[:12]}; ensure its PR is merged."
    )
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(config["url"], repo)
        if head != config["base"]:
            raise click.ClickException(
                f"Overleaf has changed since commit {config['base'][:7]}. Run "
                "`asta workspace overleaf pull`, review those edits in a PR, then publish."
            )
        if CONFIG in files(repo, head):
            raise click.ClickException(
                f"Overleaf contains reserved workspace file {CONFIG}."
            )
        git("rm", "-r", "-q", "--ignore-unmatch", ".", cwd=repo)
        for name, entry in ours.items():
            write_blob(root, entry, repo / name)
        if ours:
            git("add", "-f", "--", *sorted(ours), cwd=repo)
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
                "user.email=asta-workspace@example.invalid",
            ]
        message = f"Publish workspace commit {workspace_commit[:12]}"
        git(*identity, "commit", "-q", "-m", message, cwd=repo)
        push(repo)
        published = git("rev-parse", "HEAD", cwd=repo)
    save_config(paper, config["url"], published)
    click.echo(
        f"Published Overleaf commit {published[:7]}. Commit "
        f"{(paper / CONFIG).relative_to(root)} so the next publish starts from it."
    )
