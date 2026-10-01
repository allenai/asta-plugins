"""Exercise the workspace devcontainer's Codespaces setup inside its image."""

import json
import os
import subprocess
from pathlib import Path

root = Path("/opt/asta-plugins")
config = json.loads(
    (root / "plugins/asta-tools/skills/workspace/assets/devcontainer.json").read_text()
)
auth_dir = Path.home() / ".config/asta-cli"
auth_dir.mkdir(parents=True, exist_ok=True)
(auth_dir / "migration-probe").write_text("probe")

subprocess.run(
    config["postCreateCommand"],
    shell=True,
    check=True,
    env={**os.environ, "CODESPACES": "true"},
)

assert auth_dir.is_symlink()
assert auth_dir.resolve() == Path("/workspaces/.asta-auth")
assert (auth_dir / "migration-probe").read_text() == "probe"
