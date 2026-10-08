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
            url,
            str(dest),
            cwd=dest.parent,
            env=env,
        )
    return git("rev-parse", "HEAD", cwd=dest)


def push(repo: Path) -> None:
    with credentials() as (env, options):
        git(*options, "push", "--quiet", "origin", "HEAD", cwd=repo, env=env)


def files(repo: Path, revision: str, prefix: str = "") -> dict[str, str]:
    """Map path (relative to prefix) to blob id for regular files at a revision."""
    out = git_bytes("ls-tree", "-r", "-z", revision, "--", prefix or ".", cwd=repo)
    result = {}
    for entry in filter(None, out.split(b"\0")):
        meta, path = entry.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        name = os.fsdecode(path)[len(prefix) :]
        if kind != "blob" or mode not in ("100644", "100755"):
            click.echo(f"Skipping {name}: only regular files are copied.", err=True)
            continue
        result[name] = blob
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
    config = json.loads(path.read_text())
    if not SHA.fullmatch(str(config.get("base", ""))):
        raise click.ClickException(f"{CONFIG} has no valid base commit.")
    config["url"] = validate_url(config.get("url"))
    return config


def save_config(paper: Path, url: str, base: str) -> None:
    text = json.dumps({"url": url, "base": base}, indent=2) + "\n"
    (paper / CONFIG).write_text(text)


def write_blob(repo: Path, blob: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(git_bytes("cat-file", "blob", blob, cwd=repo))


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
    root, paper, _ = resolve(project, directory)
    config = load_config(paper)
    url = validate_url(url or config.get("url"))
    require_clean(root, paper)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(url, repo)
        new = files(repo, head)
        overleaf_bib = new.pop(BIBLIOGRAPHY, None)
        new.pop(CONFIG, None)
        known = (
            config
            and not subprocess.run(
                ["git", "cat-file", "-e", config["base"] + "^{commit}"],
                cwd=repo,
                capture_output=True,
            ).returncode
        )
        # Files Overleaf deleted since the last pull; workspace-only files are kept.
        for name in (files(repo, config["base"]) if known else {}).keys() - new.keys():
            (paper / name).unlink(missing_ok=True)
        for name, blob in new.items():
            write_blob(repo, blob, paper / name)
    save_config(paper, url, head)
    root_bib = root / BIBLIOGRAPHY
    if overleaf_bib and (
        not root_bib.exists()
        or git("hash-object", "--", str(root_bib), cwd=root) != overleaf_bib
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
    if root_bib.exists():
        ours[BIBLIOGRAPHY] = git("rev-parse", f"HEAD:{BIBLIOGRAPHY}", cwd=root)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "overleaf"
        head = clone(config["url"], repo)
        if head != config["base"]:
            raise click.ClickException(
                f"Overleaf has changed since commit {config['base'][:7]}. Run "
                "`asta workspace overleaf pull`, review those edits in a PR, then publish."
            )
        git("rm", "-r", "-q", "--ignore-unmatch", ".", cwd=repo)
        for name, blob in ours.items():
            write_blob(root, blob, repo / name)
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
            ["git", "var", "GIT_COMMITTER_IDENT"], cwd=root, capture_output=True
        ).returncode:
            identity = [
                "-c",
                "user.name=Asta Workspace",
                "-c",
                "user.email=asta@allenai.org",
            ]
        message = f"Publish workspace commit {git('rev-parse', 'HEAD', cwd=root)[:12]}"
        git(*identity, "commit", "-q", "-m", message, cwd=repo)
        push(repo)
        published = git("rev-parse", "HEAD", cwd=repo)
    save_config(paper, config["url"], published)
    click.echo(
        f"Published Overleaf commit {published[:7]}. Commit "
        f"{(paper / CONFIG).relative_to(root)} so the next publish starts from it."
    )
