"""Build the fixed edited-paper demo into the rendered site, never into source."""

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import warnings
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = spec_from_file_location("refresh_demo", ROOT / "scripts/refresh-demo.py")
refresh = module_from_spec(spec)
spec.loader.exec_module(refresh)


def run(*args, cwd=None, capture=False):
    result = subprocess.run(
        args,
        cwd=cwd or ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else None


def build(site):
    site = site.resolve()
    ref = refresh.workflow_ref()
    cache = ROOT / ".asta/cache"
    missing_cache = "demo needs a workspace cache; run `asta workspace sync` first"
    if not all((cache / name).is_file() for name in ("workspace.json", "workspace.mk")):
        raise ValueError(missing_cache)
    state = json.loads((cache / "workspace.json").read_text())
    if state["repository"] != "allenai/asta-plugins" or state["ref"] != ref:
        raise ValueError("demo needs the managed archive selected in docs.yml")
    archive = cache / "archives" / state["archive_sha256"]
    if not archive.is_file():
        raise ValueError(missing_cache)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != state["archive_sha256"]:
        raise ValueError("managed archive checksum mismatch")
    baseline = run("git", "rev-parse", "HEAD", capture=True)
    if run("git", "status", "--porcelain", "--untracked-files=no", capture=True):
        raise ValueError(
            "demo needs a clean tracked checkout; commit changes and rerender"
        )
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        edited = temporary / "edited"
        assets = temporary / "assets"
        assets.mkdir()
        # Read only the two selected assets; no archive path is extracted.
        with tarfile.open(archive) as source:
            members = source.getmembers()
            for name in ("paper-preview.sh", "what-changed.py"):
                suffix = f"/plugins/asta-tools/skills/workspace/assets/{name}"
                matches = [m for m in members if m.name.endswith(suffix) and m.isfile()]
                if len(matches) != 1:
                    raise ValueError(f"managed archive has no unique {name}")
                (assets / name).write_bytes(source.extractfile(matches[0]).read())
        run("git", "worktree", "add", "--detach", str(edited), baseline)
        try:
            run(
                "git",
                "apply",
                "--index",
                str(ROOT / "scripts/demo-edits.patch"),
                cwd=edited,
            )
            run(
                "git",
                "-c",
                "user.name=Asta demo",
                "-c",
                "user.email=demo@example.invalid",
                "commit",
                "-m",
                "Apply fixed demo edits",
                cwd=edited,
            )
            changed = run("git", "rev-parse", "HEAD", cwd=edited, capture=True)
            shutil.copytree(cache, edited / ".asta/cache")
            # The worktree's docs.yml is newer than the copied cache.
            (edited / ".asta/cache/workspace.mk").touch()
            run("make", "render", cwd=edited)
            run("bash", str(assets / "paper-preview.sh"), baseline, "paper", cwd=edited)
            run(
                "python3",
                str(ROOT / "scripts/refresh-demo.py"),
                "build",
                "--old",
                str(site),
                "--new",
                str(edited / "_site"),
                "--generator",
                str(assets / "what-changed.py"),
                "--ref",
                ref,
                "--baseline-commit",
                baseline,
                "--changed-commit",
                changed,
                "--output",
                str(site / "demo/showcase"),
            )
        finally:
            try:
                run("git", "worktree", "remove", "--force", str(edited))
            except subprocess.CalledProcessError as error:
                warnings.warn(f"could not remove demo worktree: {error}", stacklevel=2)
                shutil.rmtree(edited, ignore_errors=True)
                try:
                    run("git", "worktree", "prune", "--expire", "now")
                except subprocess.CalledProcessError as error:
                    warnings.warn(
                        f"could not prune demo worktree: {error}", stacklevel=2
                    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path, nargs="?", default=Path("_site"))
    build(parser.parse_args().site)
