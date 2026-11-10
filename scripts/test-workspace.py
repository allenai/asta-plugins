"""Run one file partition of the offline workspace suite, or all files locally."""

import subprocess
import sys
from pathlib import Path


def main():
    directory, excluded, *partition = sys.argv[1:]
    shard, count = map(int, partition)
    if count < 1 or not 0 <= shard < count:
        raise SystemExit("Expected 0 <= WORKSPACE_SHARD < WORKSPACE_SHARDS")
    files = sorted(
        path
        for path in Path(directory).rglob("test_*.py")
        if not path.is_relative_to(Path(excluded))
    )
    selected = [str(path) for i, path in enumerate(files) if i % count == shard]
    if not selected:
        print(f"Workspace shard {shard}/{count} has no files")
        return
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-v", *selected]))


if __name__ == "__main__":
    main()
