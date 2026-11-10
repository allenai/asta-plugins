"""Run one file partition of the offline workspace suite, or all files locally."""

import subprocess
import sys
from pathlib import Path


def main():
    shard, count = map(int, sys.argv[1:])
    if count < 1 or not 0 <= shard < count:
        raise SystemExit("Expected 0 <= WORKSPACE_SHARD < WORKSPACE_SHARDS")
    files = sorted(Path("tests/workspace").glob("test_*.py"))
    selected = [str(path) for i, path in enumerate(files) if i % count == shard]
    if not selected:
        print(f"Workspace shard {shard}/{count} has no files")
        return
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-v", *selected]))


if __name__ == "__main__":
    main()
