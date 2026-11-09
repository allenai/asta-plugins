"""Build the public demo from the one checked-in edit, without changing the site sources.

Run with this checkout's CLI and the -tex toolchain. The caller publishes the
result through the ordinary site's existing artifact-command hook.

This publication helper requires HEAD to have been pushed to allenai/asta-plugins
and network access to fetch that commit's managed rules and extensions. It is
run by this repository's Pages jobs; it is not an offline workspace command.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def build_demo(destination):
    root = Path(__file__).resolve().parents[1]
    destination = destination.resolve()
    env = dict(os.environ)
    env["ASTA_WORKSPACE_RESOLVED_SHA"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    env["ASTA_WORKSPACE_RESOLVED_REPOSITORY"] = "allenai/asta-plugins"

    def run(*args, cwd):
        subprocess.run(args, cwd=cwd, env=env, check=True)

    with tempfile.TemporaryDirectory(prefix="asta-example-demo-") as temp:
        checkout = Path(temp) / "checkout"
        run(
            "git",
            "clone",
            "--shared",
            "--no-checkout",
            str(root),
            str(checkout),
            cwd=root,
        )
        run(
            "git",
            "checkout",
            "--detach",
            env["ASTA_WORKSPACE_RESOLVED_SHA"],
            cwd=checkout,
        )
        project = checkout / "examples/workspace"
        # Bootstrap exactly the current scaffold; no source-site preview or cache
        # is borrowed, and What changed gets the managed ignored render inputs.
        run("make", "workspace-assets", "workspace-viewers", cwd=project)
        run("git", "apply", str(root / "examples/workspace-demo.patch"), cwd=checkout)
        run("asta", "workspace", "what-changed", "--timings", "HEAD", cwd=project)
        report = project / ".asta/cache/what-changed"
        if not (report / "what-changed.html").is_file():
            raise RuntimeError("The demo did not produce What changed")
        if destination.exists():
            raise FileExistsError(
                f"Demo output would replace an existing site path: {destination}"
            )
        shutil.copytree(report, destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    build_demo(parser.parse_args().destination)
