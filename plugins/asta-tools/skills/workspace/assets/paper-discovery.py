#!/usr/bin/env python3
"""Find LaTeX papers in a workspace and papers removed by a PR."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def valid_name(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith("-")
        and not any(ord(char) < 32 or ord(char) == 127 for char in name)
    )


DOCUMENTCLASS = re.compile(r"^[^%\n]*\\documentclass\s*[\[{]", re.MULTILINE)


def main_file(
    entry: Path, label: str, files: list[str], warnings: list[str], base: str = ""
) -> str | None:
    """main.tex, else the single top-level .tex file with \\documentclass."""
    if "main.tex" in files:
        return "main.tex"

    def content(name: str) -> str:
        try:
            if base:
                return subprocess.check_output(
                    ["git", "show", f"{base}:{label}/{name}"],
                    stderr=subprocess.DEVNULL,
                ).decode(errors="replace")
            return (entry / name).read_text(errors="replace")
        except (OSError, subprocess.CalledProcessError):
            warnings.append(f"Skipped unreadable paper source: {label}/{name}")
            return ""

    found = sorted(
        name
        for name in files
        if name.endswith(".tex")
        and DOCUMENTCLASS.search(re.sub(r"%[^\n]*", "", content(name)))
    )
    if len(found) > 1:
        warnings.append(
            f"Skipped {label}: several .tex files contain \\documentclass: {', '.join(found)}"
            " (add main.tex to choose one)"
        )
    return found[0] if len(found) == 1 else None


def current_papers(root: Path, warnings: list[str]) -> dict[str, str]:
    papers = {}
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
        if name == ".":
            continue
        files = [
            file
            for file in files
            if not (entry / file).is_symlink() and (entry / file).is_file()
        ]
        if name != "paper" and not any(
            marker in files for marker in ("latexmkrc", ".latexmkrc", "overleaf.json")
        ):
            continue
        if not all(valid_name(part) for part in entry.relative_to(root).parts):
            warnings.append(f"Skipped invalid paper directory name: {name!r}")
            continue
        main = main_file(entry, name, files, warnings)
        if main is not None:
            papers[name] = main
    return papers


def base_papers(base: str, warnings: list[str]) -> set[str]:
    if not base:
        return set()
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-rz", base],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        warnings.append(
            f"Could not read paper files at base {base}; removals were omitted"
        )
        return set()
    directories: dict[str, list[str]] = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        # Symlinks and submodules are not readable LaTeX source blobs.
        if metadata.split()[0] not in {b"100644", b"100755"}:
            continue
        path = os.fsdecode(path_bytes)
        parent, separator, filename = path.rpartition("/")
        if separator:
            directories.setdefault(parent, []).append(filename)
    names = set()
    for name, files in sorted(directories.items()):
        if name != "paper" and not any(
            marker in files for marker in ("latexmkrc", ".latexmkrc", "overleaf.json")
        ):
            continue
        if not all(valid_name(part) for part in name.split("/")):
            warnings.append(f"Skipped invalid base paper directory name: {name!r}")
            continue
        if main_file(Path(name), name, files, warnings, base) is None:
            continue
        names.add(name)
    return names


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else ""
    warnings: list[str] = []
    current = current_papers(Path.cwd(), warnings)
    removed = base_papers(base, warnings) - current.keys()
    warnings = list(dict.fromkeys(warnings))
    for warning in warnings:
        print(f"::warning::{warning}", file=sys.stderr)
    print(
        json.dumps(
            {
                "papers": sorted(current),
                "main_files": current,
                "removed": sorted(removed),
                "warnings": warnings,
            }
        )
    )


if __name__ == "__main__":
    main()
