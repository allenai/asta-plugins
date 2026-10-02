"""Run the workspace post-attach preview command in a Codespaces-like container."""

import json
import os
import select
import signal
import subprocess
import time
from pathlib import Path

root = Path("/opt/asta-plugins")
config = json.loads(
    (root / "plugins/asta-tools/skills/workspace/assets/devcontainer.json").read_text()
)
command = config["postAttachCommand"]["preview"]
env = {
    **os.environ,
    "CODESPACE_NAME": "workspace-smoke",
    "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": "app.github.dev",
}
process = subprocess.Popen(
    command,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    env=env,
    start_new_session=True,
)
try:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 15)
    assert ready, "postAttachCommand did not print a preview link"
    assert process.stdout.readline().strip() == (
        "Quarto preview: https://workspace-smoke-4848.app.github.dev/"
    )
    for _ in range(60):
        response = subprocess.run(
            ["curl", "-fsS", "http://127.0.0.1:4848/"],
            capture_output=True,
            text=True,
            check=False,
        )
        if response.returncode == 0:
            assert "The preview server answers." in response.stdout
            break
        assert process.poll() is None, "postAttachCommand exited before preview started"
        time.sleep(2)
    else:
        raise AssertionError("postAttachCommand did not start the preview on port 4848")
finally:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    process.wait(timeout=10)
