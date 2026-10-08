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
    with tempfile.TemporaryDirectory() as hooks:
        result = subprocess.run(
            ["git", "--literal-pathspecs", "-c", f"core.hooksPath={hooks}", *args],
            cwd=cwd,
            env=env,
            input=data,
            capture_output=True,
        )
    if result.returncode:
        # Diagnostics may contain URLs or credential-helper output.
        if "push" in args and any(
            marker in result.stderr.lower()
            for marker in (b"non-fast-forward", b"fetch first", b"[rejected]")
        ):
            raise click.ClickException(
                "Overleaf changed during publish. Pull and review the changes before retrying."
            )
        if any(
            marker in result.stderr.lower()
            for marker in (b"authentication failed", b"could not read username", b"401")
        ):
            raise click.ClickException(
                "Overleaf authentication failed. Check your Git token or credential helper."
            )
        raise click.ClickException(
            f"Git operation failed (exit {result.returncode}). "
            "Check repository access, credentials and remote changes."
        )
    return result.stdout


def git(*args: str, **kwargs) -> str:
    return git_bytes(*args, **kwargs).decode().strip()


def validate_url(url: str) -> str:
    match = (
        re.fullmatch(
            r"https://(?:git@)?git\.overleaf\.com/([A-Za-z0-9]+)(?:\.git)?/?", url
        )
        if isinstance(url, str)
        else None
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


def parse_config(data: bytes) -> dict:
    config = json_object(data, CONFIG)
    if not isinstance(config.get("url"), str) or not SHA.fullmatch(
        str(config.get("base", ""))
    ):
        raise click.ClickException(f"Invalid {CONFIG}; expected a URL and base commit.")
    config["url"] = validate_url(config["url"])
    for key in (
        "bibliography",
        "bibliography_reconciled",
        "bibliography_reconciled_root",
    ):
        if config.get(key) is not None and not SHA.fullmatch(str(config[key])):
            raise click.ClickException(f"Invalid {CONFIG} bibliography revision.")
    return config


def load_config(paper: Path) -> dict:
    path = paper / CONFIG
    return parse_config(path.read_bytes()) if path.exists() else {}


def validate_name(name: str) -> None:
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


def safe_path(root: Path, name: str) -> Path:
    validate_name(name)
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


def current_commit(project: Path) -> str:
    try:
        return git("rev-parse", "--verify", "HEAD", cwd=project)
    except click.ClickException as exc:
        raise click.ClickException(
            "Commit the workspace before syncing Overleaf."
        ) from exc


def require_visible(project: Path, path: Path) -> None:
    rel = path.relative_to(project).as_posix()
    entries = git_bytes("ls-files", "-vz", "--", rel, cwd=project).split(b"\0")
    if any(entry and (entry[:1].islower() or entry[:1] == b"S") for entry in entries):
        raise click.ClickException(
            f"Clear assume-unchanged/skip-worktree flags on {rel} before syncing Overleaf."
        )


def require_reviewed_deletions(
    project: Path, rel: str, commit: str, config: dict, deleted: list[str]
) -> None:
    for name in deleted:
        deletion = git(
            "log",
            "-1",
            "--format=%H",
            "--diff-filter=D",
            commit,
            "--",
            f"{rel}/{name}",
            cwd=project,
        )
        if deletion:
            before = snapshot(project, f"{deletion}^", rel)
            if (
                name in before
                and CONFIG in before
                and parse_config(blob(project, before[CONFIG]))["base"]
                == config["base"]
            ):
                continue
        raise click.ClickException(
            f"Refusing to delete Overleaf file {name}: it has no committed workspace "
            "deletion since import. Commit the complete import (force-add ignored "
            "sources if needed), then remove unwanted files in a separate reviewed commit."
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
        ["git", "check-ignore", "--quiet", "--no-index", str(root)],
        cwd=project,
        capture_output=True,
    )
    if ignored.returncode == 1:
        raise click.ClickException("Ignore .asta/cache/ in .gitignore before syncing.")
    if ignored.returncode:
        raise click.ClickException(
            "Cannot check sync cache ignore rules; check the workspace Git configuration."
        )
    root.mkdir(parents=True, exist_ok=True)
    return root


def network_options(env: dict, repo: Path) -> list[str]:
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
        config = git_bytes("config", "--null", "--list", cwd=repo, env=env)
        for entry in config.split(b"\0"):
            key = entry.partition(b"\n")[0]
            if key.lower().startswith(b"credential.") and key.lower().endswith(
                b".helper"
            ):
                options += ["-c", os.fsdecode(key) + "="]
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
    config = git_bytes("config", "--null", "--list", cwd=repo)
    for entry in config.split(b"\0"):
        key, _, value = entry.partition(b"\n")
        if (
            key.lower().startswith(b"url.")
            and key.lower().endswith((b".insteadof", b".pushinsteadof"))
            and url.encode().startswith(value)
        ):
            raise click.ClickException(
                "Git URL rewrites are not supported for Overleaf."
            )
    options = network_options(env, repo)
    refs = git(*options, "ls-remote", "--symref", url, "HEAD", cwd=repo, env=env)
    branch = next(
        (line.split()[1] for line in refs.splitlines() if line.startswith("ref: ")),
        None,
    )
    if not branch or not branch.startswith("refs/heads/"):
        raise click.ClickException("Overleaf did not report its default Git branch.")
    ref = "refs/overleaf/" + branch.removeprefix("refs/heads/")
    git(*options, "fetch", "--quiet", url, f"+{branch}:{ref}", cwd=repo, env=env)
    return repo, git("rev-parse", ref, cwd=repo), branch


def snapshot(repo: Path, revision: str, prefix: str = "") -> dict[str, tuple[str, str]]:
    """Return regular-file modes and blob IDs, rejecting symlinks and submodules."""
    result = {}
    try:
        listing = git_bytes(
            "ls-tree", "-rz", "--full-tree", revision, "--", prefix or ".", cwd=repo
        )
    except click.ClickException as exc:
        raise click.ClickException(
            "Recorded Git revision is unavailable. Restore the missing history or "
            "re-import Overleaf into a new paper directory and review the result."
        ) from exc
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        name = os.fsdecode(raw_name)
        validate_name(name)
        if prefix:
            name = name.removeprefix(prefix + "/")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise click.ClickException(
                "Symlinks and submodules are not supported in papers."
            )
        result[name] = (mode, oid)
    names = {}
    for name in result:
        parts = PurePosixPath(name).parts
        for length in range(1, len(parts) + 1):
            path = "/".join(parts[:length])
            folded = path.casefold()
            if folded in names and names[folded] != path:
                raise click.ClickException(
                    "Case-only paper path collisions are not supported; rename the conflicting files in Overleaf."
                )
            names[folded] = path
    return result


def blob(repo: Path, entry: tuple[str, str]) -> bytes:
    return git_bytes("cat-file", "blob", entry[1], cwd=repo)


def replace_file(target: Path, data: bytes, mode: int | None = None) -> None:
    temporary = None
    try:
        if mode is None and target.exists():
            mode = stat.S_IMODE(target.stat().st_mode)
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=".asta-tmp-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        if mode is not None:
            temporary.chmod(mode)
        temporary.replace(target)
    except OSError as exc:
        raise click.ClickException(
            "Sync file replacement failed. Inspect the working tree before retrying; "
            "earlier files may already have been updated."
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def receipt_path(project: Path, paper: Path, url: str) -> Path:
    name = hashlib.sha256(paper.relative_to(project).as_posix().encode()).hexdigest()
    path = cache_dir(project, url) / f"published-{name}.json"
    if path.is_symlink():
        raise click.ClickException("Symlinks are not supported in cache paths.")
    return path


def expected_head(config: dict, receipt: Path, project: Path) -> str | None:
    value = (
        json_object(receipt.read_bytes(), "publish receipt") if receipt.exists() else {}
    )
    expected = config.get("base")
    commit = value.get("commit")
    if value.get("base") == expected and SHA.fullmatch(str(commit)):
        try:
            if git("merge-base", commit, "HEAD", cwd=project) == commit:
                expected = value.get("head")
        except click.ClickException:
            pass
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
    "--reconcile-bibliography",
    is_flag=True,
    help="Confirm root references.bib includes the Overleaf entries you want to keep.",
)
@click.option(
    "--project", type=click.Path(path_type=Path, file_okay=False), default=Path(".")
)
def pull(
    url: str | None, directory: str, project: Path, reconcile_bibliography: bool
) -> None:
    """Import Overleaf edits for a workspace PR; stop on overlapping local edits."""
    project, paper = resolve(project, directory)
    config = load_config(paper)
    url = validate_url(url or config.get("url") or "")
    if config and url != config["url"]:
        raise click.ClickException(
            "This paper is already connected to a different Overleaf project."
        )
    commit = current_commit(project)
    require_clean(project, paper)
    require_visible(project, paper)
    require_visible(project, project / BIBLIOGRAPHY)
    if not reconcile_bibliography:
        require_clean(project, project / BIBLIOGRAPHY)
    rel = paper.relative_to(project).as_posix()
    ours = snapshot(project, commit, rel)
    committed_bib = snapshot(project, commit, BIBLIOGRAPHY).get(BIBLIOGRAPHY)
    if committed_bib and not (project / BIBLIOGRAPHY).exists():
        raise click.ClickException(
            "Restore the deleted root references.bib before syncing Overleaf."
        )
    ours.pop(CONFIG, None)
    if BIBLIOGRAPHY in ours:
        raise click.ClickException(
            "Move paper/references.bib entries into the root references.bib first."
        )
    with credentials() as env:
        repo, head, _ = fetch(project, url, env)
    theirs = snapshot(repo, head)
    remote_bib = theirs.pop(BIBLIOGRAPHY, None)
    previous = expected_head(config, receipt_path(project, paper, url), project)
    base = snapshot(repo, previous) if previous else {}
    base_bib = base.pop(BIBLIOGRAPHY, None)
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
    bib_revision = remote_bib[1] if remote_bib else None
    reconciled = (
        reconcile_bibliography
        or data is None
        or not shared.exists()
        or (committed_bib is not None and blob(project, committed_bib) == data)
        or (
            remote_bib == base_bib
            and (
                previous != config.get("base")
                or config.get("bibliography_reconciled") == bib_revision
            )
        )
    )
    reconciled_root = None
    if data is not None and (reconcile_bibliography or not shared.exists()):
        reconciled_root = git(
            "hash-object",
            f"--path={BIBLIOGRAPHY}",
            "--stdin",
            cwd=project,
            data=shared.read_bytes() if shared.exists() else data,
        )
    elif reconciled and remote_bib != committed_bib and previous == config.get("base"):
        reconciled_root = config.get("bibliography_reconciled_root")
    # Read every blob before changing files, so a missing object cannot leave a partial import.
    contents = {name: blob(repo, merged[name]) for name in changed}
    git("update-ref", f"refs/overleaf/bases/{head}", head, cwd=repo)
    controls = sorted(
        name
        for name in changed
        if PurePosixPath(name).name in (".gitignore", ".gitattributes")
    )
    if controls:
        click.echo(
            "warning: Review imported Git tracking/diff rules: " + ", ".join(controls),
            err=True,
        )
    try:
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
            replace_file(
                target, contents[name], 0o755 if merged[name][0] == "100755" else 0o644
            )
    except OSError as exc:
        raise click.ClickException(
            "Sync filesystem update failed. Inspect the working tree before retrying; "
            "earlier files may already have been updated."
        ) from exc
    if data is not None:
        if not shared.exists():
            replace_file(shared, data)
            click.echo(
                "Imported Overleaf's bibliography to root references.bib for review."
            )
        elif (
            git("hash-object", f"--path={BIBLIOGRAPHY}", str(shared), cwd=project)
            != bib_revision
        ):
            replace_file(backup, data)
            click.echo(
                f"warning: Overleaf's references.bib differs; the root copy stays canonical. "
                f"Reconcile needed entries from {backup} before publication.",
                err=True,
            )
    if not reconciled:
        click.echo(
            "Publication is blocked until bibliography reconciliation is confirmed. "
            "Merge the needed entries into root references.bib, then pull with "
            "--reconcile-bibliography and commit the result for review.",
            err=True,
        )
    replace_file(
        paper / CONFIG,
        (
            json.dumps(
                {
                    **config,
                    "url": url,
                    "base": head,
                    "bibliography": bib_revision,
                    "bibliography_reconciled": bib_revision if reconciled else None,
                    "bibliography_reconciled_root": reconciled_root,
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )
    imported_paths = {f"{rel}/{name}" for name in merged} | {f"{rel}/{CONFIG}"}
    if data is not None:
        imported_paths.add(BIBLIOGRAPHY)
    ignored = sorted(
        os.fsdecode(name)
        for name in git_bytes(
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            rel,
            BIBLIOGRAPHY,
            cwd=project,
        ).split(b"\0")
        if name and os.fsdecode(name) in imported_paths
    )
    if ignored:
        click.echo(
            "warning: Git ignores imported files: "
            + ", ".join(ignored)
            + ". Force-add the sources you want to keep before committing the import; "
            "publication refuses omissions without a committed deletion.",
            err=True,
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
    require_visible(project, project / BIBLIOGRAPHY)
    commit = current_commit(project)
    rel = paper.relative_to(project).as_posix()
    ours = snapshot(project, commit, rel)
    if CONFIG not in ours:
        raise click.ClickException(
            "Commit the Overleaf import and connection metadata first."
        )
    config = parse_config(blob(project, ours.pop(CONFIG)))
    url = config["url"]
    if BIBLIOGRAPHY in ours:
        raise click.ClickException("Use root references.bib, not paper/references.bib.")
    shared = snapshot(project, commit, BIBLIOGRAPHY)
    if BIBLIOGRAPHY not in shared:
        raise click.ClickException(
            "Commit the shared root references.bib before publishing."
        )
    ours[BIBLIOGRAPHY] = shared[BIBLIOGRAPHY]
    receipt = receipt_path(project, paper, url)
    expected = expected_head(config, receipt, project)
    with credentials() as env:
        repo, head, branch = fetch(project, url, env)
        if head != expected:
            raise click.ClickException(
                "Overleaf has edits that are not in the workspace. "
                "Pull and review them in a PR before publishing; nothing was pushed. "
                "A publication from another clone or a cleared cache also requires a fresh pull."
            )
        remote = snapshot(repo, head)
        remote_bib = remote.get(BIBLIOGRAPHY)
        confirmed_root = config.get("bibliography_reconciled_root")
        if (
            expected == config["base"]
            and confirmed_root is not None
            and ours[BIBLIOGRAPHY][1] != confirmed_root
        ):
            raise click.ClickException(
                "Commit the root references.bib used for reconciliation together with "
                "overleaf.json, or repeat pull --reconcile-bibliography with the intended "
                "root copy; nothing was pushed."
            )
        if (
            remote_bib is not None
            and remote_bib[1] != ours[BIBLIOGRAPHY][1]
            and not (
                expected != config["base"]
                or remote_bib[1] == config.get("bibliography_reconciled")
            )
        ):
            raise click.ClickException(
                "Overleaf references.bib has unreconciled entries. Merge the needed "
                "entries into the root bibliography, then pull with "
                "--reconcile-bibliography and commit for review; nothing was pushed."
            )
        changed = sorted(name for name in ours if ours[name] != remote.get(name))
        deleted = sorted(remote.keys() - ours.keys())
        require_reviewed_deletions(project, rel, commit, config, deleted)
        if not changed and not deleted:
            click.echo("Overleaf is already up to date.")
            return
        if changed:
            click.echo("Changed: " + ", ".join(changed))
        if deleted:
            click.echo("Deleted: " + ", ".join(deleted))
        if dry_run:
            click.echo("Dry run: nothing pushed.")
            return
        with tempfile.TemporaryDirectory() as tmp:
            index_env = dict(env, GIT_INDEX_FILE=str(Path(tmp) / "index"))
            git("read-tree", "--empty", cwd=repo, env=index_env)
            for name, entry in sorted(ours.items()):
                stored = git(
                    "hash-object", "-w", "--stdin", cwd=repo, data=blob(project, entry)
                )
                git(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    entry[0],
                    stored,
                    name,
                    cwd=repo,
                    env=index_env,
                )
            tree = git("write-tree", cwd=repo, env=index_env)
            try:
                configured = git("var", "GIT_AUTHOR_IDENT", cwd=project)
                name, address = configured.rsplit(" <", 1)
                email = address.split(">", 1)[0]
            except click.ClickException:
                name, email = "Asta workspace", "asta@allenai.org"
            new = git(
                "-c",
                f"user.name={name}",
                "-c",
                f"user.email={email}",
                "commit-tree",
                tree,
                "-p",
                head,
                cwd=repo,
                data=f"Publish reviewed workspace changes\n\n{TRAILER} {commit}\n".encode(),
            )
        git(
            *network_options(env, repo),
            "push",
            "--quiet",
            url,
            f"{new}:{branch}",
            cwd=repo,
            env=env,
        )
        git("update-ref", "refs/overleaf/published", new, cwd=repo)
    replace_file(
        receipt,
        (
            json.dumps({"base": config["base"], "head": new, "commit": commit}) + "\n"
        ).encode(),
    )
    click.echo(f"Published {rel}/ at {commit[:7]} to Overleaf.")
