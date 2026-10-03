#!/usr/bin/env python3
"""Find LaTeX papers in a workspace and papers removed by a PR."""

import json
import os
import subprocess
import sys
from pathlib import Path


def valid_name(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith("-")
        and not any(ord(char) < 32 or ord(char) == 127 for char in name)
    )


def current_papers(root: Path) -> set[str]:
    papers = set()
    for directory, children, files in os.walk(root, followlinks=False):
        entry = Path(directory)
        children[:] = [
            name
            for name in children
            if name not in {"_site", "_extensions", "build", "node_modules"}
            and not name.startswith(".")
            and not (entry / name).is_symlink()
        ]
        name = entry.relative_to(root).as_posix()
        if name == "." or "main.tex" not in files:
            continue
        if name != "paper" and not any(
            rc in files for rc in ("latexmkrc", ".latexmkrc")
        ):
            continue
        if not all(valid_name(part) for part in entry.relative_to(root).parts):
            raise ValueError(f"invalid paper directory name: {name!r}")
        papers.add(name)
    return papers


def base_papers(base: str) -> set[str]:
    if not base:
        return set()
    result = subprocess.run(
        ["git", "ls-tree", "-rz", "--name-only", base],
        capture_output=True,
        check=True,
    )
    paths = {os.fsdecode(path) for path in result.stdout.split(b"\0") if path}
    names = set()
    for path in paths:
        parts = path.split("/")
        if len(parts) < 2 or parts[-1] != "main.tex":
            continue
        name = "/".join(parts[:-1])
        if name != "paper" and not any(
            f"{name}/{rc}" in paths for rc in ("latexmkrc", ".latexmkrc")
        ):
            continue
        if not all(valid_name(part) for part in parts[:-1]):
            raise ValueError(f"invalid base paper directory name: {name!r}")
        names.add(name)
    return names


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else ""
    current = current_papers(Path.cwd())
    removed = base_papers(base) - current
    print(json.dumps({"papers": sorted(current), "removed": sorted(removed)}))


if __name__ == "__main__":
    main()
