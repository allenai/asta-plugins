"""Run the workspace post-attach preview command in a Codespaces-like container."""

import argparse
import json
import os
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
expected = "Quarto preview: https://workspace-smoke-4848.app.github.dev/"

with tempfile.TemporaryDirectory() as directory:
    log_path = Path(directory) / "preview.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
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
        except Exception:
            print(log_path.read_text(errors="replace"), file=sys.stderr)
            raise
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
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
