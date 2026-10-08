"""Import and publish reviewed paper snapshots through Overleaf's Git bridge."""

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import click

CONFIG = "overleaf.json"
BIBLIOGRAPHY = "references.bib"
TRAILER = "Asta-Workspace-Commit:"
SHA = re.compile(r"[0-9a-f]{40}")


def git_bytes(*args: str, cwd: Path, env: dict | None = None, data=None) -> bytes:
    result = subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        env=env,
        input=data,
        capture_output=True,
    )
    if result.returncode:
        # Diagnostics may contain URLs or credential-helper output.
        raise click.ClickException(
            f"Git operation failed (exit {result.returncode}). "
            "Check repository access, credentials and remote changes."
        )
    return result.stdout


def git(*args: str, **kwargs) -> str:
    return git_bytes(*args, **kwargs).decode().strip()


def validate_url(url: str) -> str:
    match = re.fullmatch(
        r"https://(?:git@)?git\.overleaf\.com/([A-Za-z0-9]+)(?:\.git)?/?", url
    )
    if not match:
        raise click.ClickException(
            "Use https://git.overleaf.com/<project-id>, without a password, "
            "query string or fragment. Other Git hosts are not supported."
        )
    return f"https://git.overleaf.com/{match[1]}"


@contextmanager
def credentials():
    """Use the token for validated Overleaf requests, or normal Git helpers."""
    env = dict(os.environ)
    if not env.get("OVERLEAF_TOKEN"):
        yield env
        return
    with tempfile.TemporaryDirectory() as tmp:
        askpass = Path(tmp) / "askpass"
        askpass.write_text(
            '#!/bin/sh\ncase "$1" in Username*) echo git;; *) echo "$OVERLEAF_TOKEN";; esac\n'
        )
        askpass.chmod(stat.S_IRWXU)
        env.update(GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT="0")
        yield env


def json_object(data: bytes, description: str) -> dict:
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeError) as exc:
        raise click.ClickException(f"Invalid {description} JSON.") from exc


def load_config(paper: Path) -> dict:
    path = paper / CONFIG
    config = json_object(path.read_bytes(), CONFIG) if path.exists() else {}
    if config:
        if not isinstance(config.get("url"), str) or not SHA.fullmatch(
            str(config.get("base", ""))
        ):
            raise click.ClickException(
                f"Invalid {CONFIG}; expected a URL and base commit."
            )
        config["url"] = validate_url(config["url"])
    return config


def safe_path(root: Path, name: str) -> Path:
    parts = PurePosixPath(name).parts
    if (
        not parts
        or name.startswith("/")
        or "\\" in name
        or any(
            part in (".", "..") or part.lower() in (".git", ".asta") for part in parts
        )
    ):
        raise click.ClickException(
            "Paper paths must be relative and outside .git/.asta."
        )
    target = root / name
    for path in [target, *target.parents]:
        if path == root:
            break
        if path.is_symlink():
            raise click.ClickException(
                "Symlinks are not supported in paper or cache paths."
            )
    return target


def resolve(project: Path, directory: str) -> tuple[Path, Path]:
    project = Path(git("rev-parse", "--show-toplevel", cwd=project.resolve()))
    if directory in ("", ".") or Path(directory).is_absolute():
        raise click.ClickException("--dir must name a paper subdirectory.")
    paper = safe_path(project, directory)
    safe_path(project, f"{directory}/{CONFIG}")
    return project, paper


def require_clean(project: Path, path: Path) -> None:
    rel = path.relative_to(project).as_posix()
    if git("status", "--porcelain", "--untracked-files=all", "--", rel, cwd=project):
        raise click.ClickException(
            f"{rel} has uncommitted changes; commit or stash them first."
        )


def cache_dir(project: Path, url: str) -> Path:
    root = project / ".asta/cache/overleaf" / hashlib.sha256(url.encode()).hexdigest()
    for path in [root, *root.parents]:
        if path == project:
            break
        if path.is_symlink():
            raise click.ClickException("Symlinks are not supported in cache paths.")
    if git("ls-files", "--", ".asta/cache", cwd=project):
        raise click.ClickException(
            "The sync cache must not be committed; untrack .asta/cache/ first."
        )
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", str(root)], cwd=project
    )
    if ignored.returncode:
        raise click.ClickException("Ignore .asta/cache/ in .gitignore before syncing.")
    root.mkdir(parents=True, exist_ok=True)
    return root


def network_options(env: dict) -> list[str]:
    options = [
        "-c",
        "http.followRedirects=false",
        "-c",
        "http.extraHeader=",
        "-c",
        "credential.username=git",
    ]
    if env.get("OVERLEAF_TOKEN"):
        options += ["-c", "credential.helper="]
    return options


def fetch(project: Path, url: str, env: dict) -> tuple[Path, str, str]:
    """Keep history as bare objects; never check out or execute remote files."""
    repo = cache_dir(project, url) / "repo.git"
    if repo.is_symlink():
        raise click.ClickException("Symlinks are not supported in cache paths.")
    if not repo.exists():
        git("init", "--quiet", "--bare", str(repo), cwd=project)
    if git("ls-remote", "--get-url", url, cwd=repo) != url:
        raise click.ClickException("Git URL rewrites are not supported for Overleaf.")
    options = network_options(env)
    refs = git(*options, "ls-remote", "--symref", url, "HEAD", cwd=repo, env=env)
    branch = next(
        (line.split()[1] for line in refs.splitlines() if line.startswith("ref: ")),
        None,
    )
    if not branch or not branch.startswith("refs/heads/"):
        raise click.ClickException("Overleaf did not report its default Git branch.")
    git(*options, "fetch", "--quiet", url, branch, cwd=repo, env=env)
    return repo, git("rev-parse", "FETCH_HEAD", cwd=repo), branch


def snapshot(repo: Path, revision: str, prefix: str = "") -> dict[str, str]:
    """Return regular-file blob IDs, rejecting symlinks and submodules up front."""
    result = {}
    listing = git_bytes(
        "ls-tree", "-rz", "--full-tree", revision, "--", prefix or ".", cwd=repo
    )
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        name = os.fsdecode(raw_name)
        safe_path(repo, name)
        if prefix:
            name = name.removeprefix(prefix + "/")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise click.ClickException(
                "Symlinks and submodules are not supported in papers."
            )
        result[name] = oid
    return result


def blob(repo: Path, oid: str) -> bytes:
    return git_bytes("cat-file", "blob", oid, cwd=repo)


def receipt_path(project: Path, paper: Path, url: str) -> Path:
    name = hashlib.sha256(paper.relative_to(project).as_posix().encode()).hexdigest()
    path = cache_dir(project, url) / f"published-{name}.json"
    if path.is_symlink():
        raise click.ClickException("Symlinks are not supported in cache paths.")
    return path


def expected_head(config: dict, receipt: Path) -> str | None:
    value = (
        json_object(receipt.read_bytes(), "publish receipt") if receipt.exists() else {}
    )
    expected = (
        value.get("head")
        if value.get("base") == config.get("base") and config
        else config.get("base")
    )
    if expected is not None and not SHA.fullmatch(str(expected)):
        raise click.ClickException(
            "Invalid recorded Overleaf revision; restore the connection metadata."
        )
    return expected


def merge_files(base: dict, ours: dict, theirs: dict) -> dict:
    merged, conflicts = {}, []
    for name in sorted(base.keys() | ours.keys() | theirs.keys()):
        old, local, remote = base.get(name), ours.get(name), theirs.get(name)
        if local == old or local == remote:
            chosen = remote
        elif remote == old:
            chosen = local
        else:
            conflicts.append(name)
            continue
        if chosen is not None:
            merged[name] = chosen
    for name in merged:
        if any(parent.as_posix() in merged for parent in PurePosixPath(name).parents):
            conflicts.append(name)
    if conflicts:
        raise click.ClickException(
            "Both workspace and Overleaf changed these paths: "
            + ", ".join(conflicts)
            + ". Reconcile them before pulling; no workspace files were changed."
        )
    return merged


@click.group()
def overleaf() -> None:
    """Pull and publish papers with Overleaf Git tokens or Git credential helpers."""


@overleaf.command()
@click.argument("url", required=False)
@click.option("--dir", "directory", default="paper", show_default=True)
@click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
def pull(url: str | None, directory: str, project: Path) -> None:
    """Import Overleaf edits for a workspace PR; stop on overlapping local edits."""
    project, paper = resolve(project, directory)
    config = load_config(paper)
    url = validate_url(url or config.get("url") or "")
    if config and url != config["url"]:
        raise click.ClickException(
            "This paper is already connected to a different Overleaf project."
        )
    require_clean(project, paper)
    rel = paper.relative_to(project).as_posix()
    ours = snapshot(project, "HEAD", rel)
    ours.pop(CONFIG, None)
    if BIBLIOGRAPHY in ours:
        raise click.ClickException(
            "Move paper/references.bib entries into the root references.bib first."
        )
    with credentials() as env:
        repo, head, _ = fetch(project, url, env)
    theirs = snapshot(repo, head)
    remote_bib = theirs.pop(BIBLIOGRAPHY, None)
    previous = expected_head(config, receipt_path(project, paper, url))
    base = snapshot(repo, previous) if previous else {}
    base.pop(BIBLIOGRAPHY, None)
    if CONFIG in theirs or CONFIG in base:
        raise click.ClickException(
            "overleaf.json is reserved for workspace connection metadata."
        )
    merged = merge_files(base, ours, theirs)
    changed = {name for name in merged if merged[name] != ours.get(name)}
    removed = ours.keys() - merged.keys()
    for name in changed:
        target = safe_path(paper, name)
        if target.exists() and name not in ours and not target.is_dir():
            raise click.ClickException(
                f"An untracked file blocks import: {name}. Move it first."
            )
        if target.is_dir():
            for child in target.rglob("*"):
                if child.is_symlink() or (
                    child.is_file()
                    and child.relative_to(paper).as_posix() not in removed
                ):
                    raise click.ClickException(
                        f"Existing directory blocks import: {name}."
                    )
        for parent in target.parents:
            if parent == paper:
                break
            if parent.is_file() and parent.relative_to(paper).as_posix() not in removed:
                raise click.ClickException(f"Existing file blocks import: {name}.")
    shared = safe_path(project, BIBLIOGRAPHY)
    if shared.exists() and not shared.is_file():
        raise click.ClickException("Root references.bib must be a regular file.")
    data = blob(repo, remote_bib) if remote_bib else None
    backup = cache_dir(project, url) / "overleaf-references.bib"
    if backup.is_symlink():
        raise click.ClickException("Symlinks are not supported in cache paths.")
    paper.mkdir(parents=True, exist_ok=True)
    for name in sorted(removed, reverse=True):
        safe_path(paper, name).unlink()
    for name in sorted(changed):
        target = safe_path(paper, name)
        if target.is_dir():
            for child in sorted(target.rglob("*"), reverse=True):
                child.rmdir()
            target.rmdir()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob(repo, merged[name]))
    if data is not None:
        if not shared.exists():
            shared.write_bytes(data)
            click.echo(
                "Imported Overleaf's bibliography to root references.bib for review."
            )
        elif shared.read_bytes() != data:
            backup.write_bytes(data)
            click.echo(
                f"warning: Overleaf's references.bib differs; the root copy stays canonical. "
                f"Reconcile needed entries from {backup} before publication.",
                err=True,
            )
    (paper / CONFIG).write_text(
        json.dumps({**config, "url": url, "base": head}, indent=2) + "\n"
    )
    click.echo(
        f"Pulled Overleaf {head[:7]} into {rel}/, preserving committed local edits."
    )
    click.echo("Commit on a branch and open a PR to preview before publishing.")


@overleaf.command()
@click.option("--dir", "directory", default="paper", show_default=True)
@click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
@click.option("--dry-run", is_flag=True, help="Show changes; push nothing.")
def publish(directory: str, project: Path, dry_run: bool) -> None:
    """Publish the committed snapshot after review, refusing intervening remote edits."""
    project, paper = resolve(project, directory)
    config = load_config(paper)
    if not config:
        raise click.ClickException("Run `asta workspace overleaf pull <url>` first.")
    require_clean(project, paper)
    require_clean(project, project / BIBLIOGRAPHY)
    commit = git("rev-parse", "HEAD", cwd=project)
    rel = paper.relative_to(project).as_posix()
    ours = snapshot(project, commit, rel)
    if CONFIG not in ours:
        raise click.ClickException(
            "Commit the Overleaf import and connection metadata first."
        )
    config = json_object(blob(project, ours.pop(CONFIG)), CONFIG)
    url = validate_url(config["url"])
    if BIBLIOGRAPHY in ours:
        raise click.ClickException("Use root references.bib, not paper/references.bib.")
    shared = snapshot(project, commit, BIBLIOGRAPHY)
    if BIBLIOGRAPHY not in shared:
        raise click.ClickException(
            "Commit the shared root references.bib before publishing."
        )
    ours[BIBLIOGRAPHY] = shared[BIBLIOGRAPHY]
    receipt = receipt_path(project, paper, url)
    expected = expected_head(config, receipt)
    with credentials() as env:
        repo, head, branch = fetch(project, url, env)
        if head != expected:
            raise click.ClickException(
                "Overleaf has edits that are not in the workspace. "
                "Pull and review them in a PR before publishing; nothing was pushed."
            )
        remote = snapshot(repo, head)
        changed = sorted(name for name in ours if ours[name] != remote.get(name))
        deleted = sorted(remote.keys() - ours.keys())
        if not changed and not deleted:
            click.echo("Overleaf is already up to date.")
            return
        click.echo("Changed: " + ", ".join(changed))
        click.echo("Deleted: " + ", ".join(deleted))
        if dry_run:
            click.echo("Dry run: nothing pushed.")
            return
        with tempfile.TemporaryDirectory() as tmp:
            index_env = dict(env, GIT_INDEX_FILE=str(Path(tmp) / "index"))
            git("read-tree", "--empty", cwd=repo, env=index_env)
            for name, oid in sorted(ours.items()):
                stored = git(
                    "hash-object", "-w", "--stdin", cwd=repo, data=blob(project, oid)
                )
                git(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    "100644",
                    stored,
                    name,
                    cwd=repo,
                    env=index_env,
                )
            tree = git("write-tree", cwd=repo, env=index_env)
            new = git(
                "-c",
                "user.name=Asta workspace",
                "-c",
                "user.email=asta@allenai.org",
                "commit-tree",
                tree,
                "-p",
                head,
                cwd=repo,
                data=f"Publish reviewed workspace changes\n\n{TRAILER} {commit}\n".encode(),
            )
        git(
            *network_options(env),
            "push",
            "--quiet",
            url,
            f"{new}:{branch}",
            cwd=repo,
            env=env,
        )
    receipt.write_text(json.dumps({"base": config["base"], "head": new}) + "\n")
    click.echo(f"Published {rel}/ at {commit[:7]} to Overleaf.")
