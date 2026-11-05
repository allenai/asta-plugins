"""Build the fixed edited-paper demo into the rendered site, never into source."""

import shutil
import subprocess
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
    repo = Path(run("git", "rev-parse", "--show-toplevel", capture=True))
    project = ROOT.relative_to(repo)
    baseline = run("git", "rev-parse", "HEAD", capture=True)
    if run("git", "status", "--porcelain", "--untracked-files=no", capture=True):
        raise ValueError(
            "demo needs a clean tracked checkout; commit changes and rerender"
        )
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        edited = temporary / "edited"
        # The edited worktree's own assets build the demo, matching the release.
        assets = edited / "plugins/asta-tools/skills/workspace/assets"
        run("git", "worktree", "add", "--detach", str(edited), baseline)
        try:
            run(
                "git",
                "apply",
                "--index",
                *([f"--directory={project}"] if project != Path(".") else []),
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
            run("make", "render", cwd=edited / project)
            run(
                "bash",
                str(assets / "paper-preview.sh"),
                baseline,
                "paper",
                cwd=edited / project,
            )
            run(
                "python3",
                str(ROOT / "scripts/refresh-demo.py"),
                "build",
                "--old",
                str(site),
                "--new",
                str(edited / project / "_site"),
                "--generator",
                str(assets / "what-changed.py"),
                "--ref",
                ref,
                "--baseline-commit",
                baseline,
                "--changed-commit",
                changed,
                "--output",
                str(site / "demo"),
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
