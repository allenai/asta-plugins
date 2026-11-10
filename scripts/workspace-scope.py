"""Return true when a PR can affect workspace checks (renames included)."""

import os
import subprocess
import sys

paths = subprocess.check_output(
    ["git", "diff", "--name-only", "--no-renames", "-z", sys.argv[1], "HEAD"], text=True
).split("\0")
prefixes = tuple(os.environ["WORKSPACE_PATHS"].split())
if not prefixes:
    raise ValueError("WORKSPACE_PATHS must define workspace ownership")
print(str(any(path.startswith(prefixes) for path in paths)).lower())
