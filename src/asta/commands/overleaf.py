"""Sync a workspace paper directory with an Overleaf project over Git.

The workspace repo is the reviewed copy: `pull` brings Overleaf edits into the
paper directory for a PR, and `publish` pushes the reviewed directory back. The
Overleaf clone lives in the git-ignored `.asta/cache/overleaf/`; credentials
come from Git's credential helpers or `OVERLEAF_TOKEN`, never from this repo.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

import click

CONFIG = "overleaf.json"
BIBLIOGRAPHY = "references.bib"
TRAILER = "Asta-Workspace-Commit:"


def git(*args: str, cwd: Path, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True
    )
    if result.returncode:
        raise click.ClickException(
            f"git {' '.join(args)} failed:\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


@contextmanager
def credentials():
    """Supply OVERLEAF_TOKEN to Git without writing it to any config or URL."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    token = os.environ.get("OVERLEAF_TOKEN")
    if not token:
        env.pop("GIT_TERMINAL_PROMPT")
        yield env
        return
    with tempfile.TemporaryDirectory() as tmp:
        askpass = Path(tmp) / "askpass"
        askpass.write_text(
            '#!/bin/sh\ncase "$1" in Username*) echo git;; *) echo "$OVERLEAF_TOKEN";; esac\n'
        )
        askpass.chmod(stat.S_IRWXU)
        env["GIT_ASKPASS"] = str(askpass)
        yield env


def load_config(paper: Path) -> dict:
    path = paper / CONFIG
    return json.loads(path.read_text()) if path.exists() else {}


def save_config(paper: Path, config: dict) -> None:
    (paper / CONFIG).write_text(json.dumps(config, indent=2) + "\n")


def clone_dir(project: Path, url: str) -> Path:
    name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "project"
    return project / ".asta" / "cache" / "overleaf" / name


def fetch(project: Path, url: str, env: dict) -> Path:
    """Clone or update the cached Overleaf checkout; returns its path."""
    clone = clone_dir(project, url)
    if not (clone / ".git").exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--quiet", url, str(clone), cwd=project, env=env)
    else:
        git("fetch", "--quiet", "origin", cwd=clone, env=env)
        branch = git("rev-parse", "--abbrev-ref", "origin/HEAD", cwd=clone)
        git(
            "checkout",
            "--quiet",
            "--force",
            "-B",
            branch.split("/", 1)[1],
            branch,
            cwd=clone,
        )
        git("clean", "-fdxq", cwd=clone)
    return clone


def tracked(repo: Path, rev: str = "HEAD", path: str = ".") -> set[str]:
    out = git("ls-tree", "-r", "--name-only", "--full-tree", rev, "--", path, cwd=repo)
    return set(out.splitlines()) if out else set()


def require_clean(project: Path, paper: Path) -> None:
    rel = paper.relative_to(project).as_posix()
    if git("status", "--porcelain", "--", rel, cwd=project):
        raise click.ClickException(
            f"{rel}/ has uncommitted changes; commit or stash them first."
        )


def resolve(project: Path, directory: str) -> tuple[Path, Path]:
    project = project.resolve()
    git("rev-parse", "--show-toplevel", cwd=project)
    return project, project / directory


@click.group()
def overleaf() -> None:
    """Pull from and publish to an Overleaf project with its Git integration.

    Authenticate with an Overleaf Git token: set OVERLEAF_TOKEN, or let Git's
    credential helper prompt once (username `git`, password = the token).
    """


@overleaf.command()
@click.argument("url", required=False)
@click.option("--dir", "directory", default="paper", show_default=True)
@click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
def pull(url: str | None, directory: str, project: Path) -> None:
    """Copy the Overleaf project into the paper directory for review.

    The first pull needs the project's Git URL (Overleaf: Menu > Integrations >
    Git); it is saved in <dir>/overleaf.json. Commit the result on a branch and
    open a PR so the changes get a preview before anything is published.
    """
    project, paper = resolve(project, directory)
    config = load_config(paper)
    url = url or config.get("url")
    if not url:
        raise click.UsageError("Pass the Overleaf Git URL on the first pull.")
    if paper.exists():
        require_clean(project, paper)
    with credentials() as env:
        clone = fetch(project, url, env)
    head = git("rev-parse", "HEAD", cwd=clone)
    files = tracked(clone)
    previous = config.get("base")
    removed = tracked(clone, previous) - files if previous else set()

    paper.mkdir(parents=True, exist_ok=True)
    for name in sorted(removed - {BIBLIOGRAPHY, CONFIG}):
        (paper / name).unlink(missing_ok=True)
    for name in sorted(files - {BIBLIOGRAPHY, CONFIG}):
        target = paper / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(clone / name, target)
    shared = project / BIBLIOGRAPHY
    if BIBLIOGRAPHY in files and shared.exists():
        if (clone / BIBLIOGRAPHY).read_bytes() != shared.read_bytes():
            click.echo(
                f"warning: Overleaf's {BIBLIOGRAPHY} differs from the workspace copy; "
                f"it was not imported. Make bibliography edits in {BIBLIOGRAPHY} "
                "at the project root.",
                err=True,
            )
    elif BIBLIOGRAPHY in files and not (paper / BIBLIOGRAPHY).exists():
        shutil.copy2(clone / BIBLIOGRAPHY, paper / BIBLIOGRAPHY)

    save_config(paper, {**config, "url": url, "base": head})
    rel = paper.relative_to(project).as_posix()
    click.echo(f"Pulled Overleaf {head[:7]} into {rel}/.")
    click.echo(
        f"Review with `git diff -- {rel}`, then commit on a branch and open a PR."
    )


@overleaf.command()
@click.option("--dir", "directory", default="paper", show_default=True)
@click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
@click.option("--dry-run", is_flag=True, help="Show what would change; push nothing.")
def publish(directory: str, project: Path, dry_run: bool) -> None:
    """Push the committed paper directory to Overleaf.

    Run on the reviewed commit (normally main after the PR merges). Refuses if
    anyone edited the paper in Overleaf since the last pull or publish; run
    `pull` and review those edits in a PR first, so nothing is overwritten.
    """
    project, paper = resolve(project, directory)
    config = load_config(paper)
    if not config.get("url") or not config.get("base"):
        raise click.ClickException(
            f"No {directory}/{CONFIG}; run `asta workspace overleaf pull <url>` first."
        )
    require_clean(project, paper)
    with credentials() as env:
        clone = fetch(project, config["url"], env)
        head = git("rev-parse", "HEAD", cwd=clone)
        message = git("log", "-1", "--format=%B", cwd=clone)
        if head != config["base"] and TRAILER not in message:
            raise click.ClickException(
                "Overleaf has edits that are not in the workspace "
                f"(Overleaf {head[:7]}, last pulled {config['base'][:7]}). "
                f"Run `asta workspace overleaf pull --dir {directory}`, review the "
                "changes in a PR, then publish again."
            )

        rel = paper.relative_to(project).as_posix()
        ours = {
            name.removeprefix(rel + "/") for name in tracked(project, "HEAD", rel)
        } - {CONFIG}
        for name in tracked(clone) - ours - {BIBLIOGRAPHY}:
            (clone / name).unlink()
        for name in ours:
            target = clone / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paper / name, target)
        shared = project / BIBLIOGRAPHY
        if BIBLIOGRAPHY not in ours and shared.exists():
            shutil.copy2(shared, clone / BIBLIOGRAPHY)

        git("add", "--all", cwd=clone)
        changes = git("status", "--short", cwd=clone)
        if not changes:
            click.echo("Overleaf is already up to date.")
            return
        click.echo(changes)
        if dry_run:
            git("reset", "--quiet", "--hard", cwd=clone)
            click.echo("Dry run: nothing pushed.")
            return
        commit = git("rev-parse", "HEAD", cwd=project)
        git(
            "-c",
            "user.name=Asta workspace",
            "-c",
            "user.email=asta@allenai.org",
            "commit",
            "--quiet",
            "-m",
            f"Publish reviewed workspace changes\n\n{TRAILER} {commit}",
            cwd=clone,
        )
        git("push", "--quiet", "origin", "HEAD", cwd=clone, env=env)
    click.echo(f"Published {rel}/ at {commit[:7]} to Overleaf.")
