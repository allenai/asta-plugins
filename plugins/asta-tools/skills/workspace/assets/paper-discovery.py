#!/usr/bin/env python3
"""Find LaTeX papers in a workspace and papers removed relative to a base checkout."""

import json
import os
import sys
from pathlib import Path


def valid_name(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith("-")
        and not any(ord(char) < 32 or ord(char) == 127 for char in name)
    )


def current_papers(root: Path, warnings: list[str]) -> set[str]:
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
            warnings.append(f"Skipped invalid paper directory name: {name!r}")
            continue
        papers.add(name)
    return papers


def main() -> None:
    base_dir = sys.argv[1] if len(sys.argv) > 1 else ""
    warnings: list[str] = []
    current = current_papers(Path.cwd(), warnings)
    removed = set()
    if base_dir and Path(base_dir).is_dir():
        removed = current_papers(Path(base_dir), []) - current
    elif base_dir:
        warnings.append(
            f"Could not read paper files at base {base_dir}; removals were omitted"
        )
    for warning in warnings:
        print(f"::warning::{warning}", file=sys.stderr)
    print(
        json.dumps(
            {
                "papers": sorted(current),
                "removed": sorted(removed),
                "warnings": warnings,
            }
        )
    )


if __name__ == "__main__":
    main()
