"""Build the demo through the PR preview's site-directory comparison contract.

Both full sites are rendered independently of the local What changed renderer.
The one checked-in patch is the only source of demo edits.
"""

import concurrent.futures
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from report_signature import report_signature

ROOT = Path(__file__).resolve().parents[2]


def check_preview(artifacts, local_report):
    started = time.perf_counter()
    env = dict(os.environ)
    env["ASTA_WORKSPACE_RESOLVED_SHA"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    env["ASTA_WORKSPACE_RESOLVED_REPOSITORY"] = "allenai/asta-plugins"

    def run(*args, cwd):
        subprocess.run(args, cwd=cwd, env=env, check=True)

    with tempfile.TemporaryDirectory(prefix="asta-preview-contract-") as temp:
        projects = []
        for side in ("before", "after"):
            clone = Path(temp) / side
            run(
                "git",
                "clone",
                "--shared",
                "--no-checkout",
                str(ROOT),
                str(clone),
                cwd=ROOT,
            )
            run(
                "git",
                "checkout",
                "--detach",
                env["ASTA_WORKSPACE_RESOLVED_SHA"],
                cwd=clone,
            )
            project = clone / "examples/workspace"
            projects.append(project)
            if side == "after":
                run(
                    "git",
                    "apply",
                    str(ROOT / "examples/workspace-demo.patch"),
                    cwd=clone,
                )
                # The workflow's paper builder compares committed refs. Commit
                # only in this disposable clone, leaving the checkout untouched.
                run("git", "add", "examples/workspace", cwd=clone)
                run(
                    "git",
                    "-c",
                    "user.name=Example check",
                    "-c",
                    "user.email=example@localhost",
                    "commit",
                    "-m",
                    "Apply demo edit for preview acceptance",
                    cwd=clone,
                )

        def render(project):
            # Cold scaffold bootstrap and ordinary full project render, exactly
            # as a preview build. No local comparison selector/copy helper runs.
            run("make", "render", cwd=project)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(render, projects))
        after = projects[1]
        discovery = subprocess.check_output(
            [
                sys.executable,
                str(
                    ROOT
                    / "plugins/asta-tools/skills/workspace/assets/paper-discovery.py"
                ),
                env["ASTA_WORKSPACE_RESOLVED_SHA"],
            ],
            cwd=after,
            env=env,
            text=True,
        )
        import json

        for paper in json.loads(discovery)["papers"]:
            run(
                "bash",
                str(
                    ROOT / "plugins/asta-tools/skills/workspace/assets/paper-preview.sh"
                ),
                env["ASTA_WORKSPACE_RESOLVED_SHA"],
                paper,
                cwd=after,
            )
        run(
            "asta",
            "workspace",
            "what-changed",
            "--timings",
            "--before-site",
            str(projects[0] / "_site"),
            "--after-site",
            str(after / "_site"),
            cwd=after,
        )
        spec = importlib.util.spec_from_file_location(
            "demo_acceptance", ROOT / "tests/browser/local-what-changed-demo.py"
        )
        acceptance = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(acceptance)
        acceptance.check_site(after / "_site", artifacts)
        assert report_signature(after / "_site") == report_signature(local_report), (
            "Independent preview and local demo disagree on pages or marked words"
        )
        # Retain the independent result for comparing with the local report.
        output = artifacts / "preview-path-site"
        shutil.copytree(after / "_site", output)
    print(
        f"Independent preview-path total: {time.perf_counter() - started:.2f} s",
        file=sys.stderr,
    )


if __name__ == "__main__":
    check_preview(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
