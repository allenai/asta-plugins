"""Return true when a PR can affect workspace checks (renames included)."""

import os
import subprocess
import sys

paths = subprocess.check_output(
    ["git", "diff", "--name-only", "--no-renames", sys.argv[1], "HEAD"], text=True
).splitlines()
prefixes = tuple(os.environ["WORKSPACE_PATHS"].split())
print(str(any(path.startswith(prefixes) for path in paths)).lower())
