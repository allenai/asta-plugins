"""Run the workspace post-attach preview command in a Codespaces-like container."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--preview-command", choices=("asset", "cli"), default="asset")
mode = parser.parse_args().preview_command

root = Path("/opt/asta-plugins")
config = json.loads(
    (root / "plugins/asta-tools/skills/workspace/assets/devcontainer.json").read_text()
)
command = (
    "asta workspace preview"
    if mode == "cli"
    else config["postAttachCommand"]["preview"]
)
env = {
    **os.environ,
    "CODESPACE_NAME": "workspace-smoke",
    "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": "app.github.dev",
}
label = "Preview" if mode == "cli" else "Quarto preview"
expected = f"{label}: https://workspace-smoke-4848.app.github.dev/"

with tempfile.TemporaryDirectory() as directory:
    project = Path.cwd()
    if mode == "cli":
        project = Path(directory) / "project"
        project.mkdir()
        for name in ("_quarto.yml", "index.qmd"):
            shutil.copyfile(Path.cwd() / name, project / name)
        # A project-owned Makefile need not provide the shared preview target.
        (project / "Makefile").write_text("check:\n\t@true\n")
    log_path = Path(directory) / "preview.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            ["asta", "workspace", "preview"] if mode == "cli" else command,
            shell=mode != "cli",
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=project,
            start_new_session=True,
        )
        try:
            for _ in range(150):
                if expected in log_path.read_text(errors="replace").splitlines():
                    break
                if process.poll() is not None:
                    raise AssertionError(
                        "postAttachCommand exited before printing the link"
                    )
                time.sleep(0.1)
            else:
                raise AssertionError("postAttachCommand did not print the preview link")

            for _ in range(60):
                response = subprocess.run(
                    ["curl", "-fsS", "--max-time", "5", "http://127.0.0.1:4848/"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if response.returncode == 0:
                    if "The preview server answers." not in response.stdout:
                        raise AssertionError("preview response lacks fixture content")
                    break
                if process.poll() is not None:
                    raise AssertionError(
                        "postAttachCommand exited before preview started"
                    )
                time.sleep(2)
            else:
                raise AssertionError(
                    "postAttachCommand did not start preview on port 4848"
                )
            if mode == "cli":
                # Rerunning for the same project reuses the live preview.
                rerun = subprocess.run(
                    ["asta", "workspace", "preview", "--project", str(project)],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=15,
                    check=False,
                )
                if rerun.returncode != 0 or (
                    f"Preview already running: {expected.split(': ', 1)[1]}"
                    not in rerun.stdout
                ):
                    raise AssertionError(
                        "CLI must reuse this project's running preview\n"
                        f"stdout: {rerun.stdout}\nstderr: {rerun.stderr}"
                    )
                # Another project must not mistake that server for its own.
                other = Path(directory) / "other"
                shutil.copytree(project, other, ignore=shutil.ignore_patterns(".asta"))
                occupied = subprocess.run(
                    ["asta", "workspace", "preview", "--project", str(other)],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=15,
                    check=False,
                )
                if occupied.returncode == 0 or "in use by another process" not in (
                    occupied.stderr
                ):
                    raise AssertionError(
                        "CLI must report a preview port held by another project\n"
                        f"stdout: {occupied.stdout}\nstderr: {occupied.stderr}"
                    )
                process.send_signal(signal.SIGINT)
                if process.wait(timeout=6) != 130:
                    raise AssertionError("Interrupted CLI must exit with status 130")
                if (project / ".asta/cache/preview.json").exists():
                    raise AssertionError("Interrupted CLI left preview ownership state")
                for _ in range(20):
                    response = subprocess.run(
                        ["curl", "-fsS", "--max-time", "1", "http://127.0.0.1:4848/"],
                        capture_output=True,
                        check=False,
                    )
                    if response.returncode != 0:
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("Preview kept serving after CLI interruption")
        except Exception:
            print(log_path.read_text(errors="replace"), file=sys.stderr)
            raise
        finally:
            try:
                os.killpg(
                    process.pid, signal.SIGINT if mode == "cli" else signal.SIGTERM
                )
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
