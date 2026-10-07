"""Exercise the workspace devcontainer's Codespaces setup inside its image."""

import argparse
import json
import os
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("phase", choices=("initial", "rebuild"))
phase = parser.parse_args().phase

root = Path("/opt/asta-plugins")
config = json.loads(
    (root / "plugins/asta-tools/skills/workspace/assets/devcontainer.json").read_text()
)
auth_dir = Path.home() / ".config/asta-cli"
if phase == "initial":
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "migration-probe").write_text("probe")
elif phase == "rebuild":
    if auth_dir.exists():
        raise AssertionError("rebuild should start with a fresh container home")
else:
    raise ValueError(f"unknown phase: {phase}")

# The image's devcontainer.metadata hook runs before the project's own command.
for command in ("asta-persist-auth", config["postCreateCommand"]):
    subprocess.run(
        command,
        shell=True,
        check=True,
        env={**os.environ, "CODESPACES": "true"},
    )

assert auth_dir.is_symlink()
assert auth_dir.resolve() == Path("/workspaces/.asta-auth")
assert (auth_dir / "migration-probe").read_text() == "probe"
