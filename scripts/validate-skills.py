#!/usr/bin/env python3
"""Validate SKILL.md frontmatter against the Agent Skills spec.

Checks every plugins/asta-tools/skills/*/SKILL.md for:
- `name`: kebab-case (`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`), max 64, matches parent dir
- `description`: 1-1024 chars, non-empty
- `allowed-tools`: space-separated string (not a YAML list)

See https://agentskills.io/specification.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
REPO_ROOT = Path(__file__).resolve().parents[1]


def validate(skill_md: Path) -> list[str]:
    errors: list[str] = []
    raw = skill_md.read_text()
    if not raw.startswith("---\n"):
        return [f"{skill_md}: missing YAML frontmatter"]
    try:
        end = raw.index("\n---\n", 4)
    except ValueError:
        return [f"{skill_md}: unterminated frontmatter"]
    fm = yaml.safe_load(raw[4:end]) or {}

    name = fm.get("name")
    if not isinstance(name, str):
        errors.append(f"{skill_md}: `name` missing or not a string")
    else:
        if len(name) > 64 or not NAME_PATTERN.match(name):
            errors.append(
                f"{skill_md}: `name` {name!r} must be kebab-case "
                "(`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`, max 64)"
            )
        if name != skill_md.parent.name:
            errors.append(
                f"{skill_md}: `name` {name!r} must match parent dir "
                f"{skill_md.parent.name!r}"
            )

    desc = fm.get("description")
    if not isinstance(desc, str) or not desc:
        errors.append(f"{skill_md}: `description` missing or empty")
    elif len(desc) > 1024:
        errors.append(f"{skill_md}: `description` exceeds 1024 chars ({len(desc)})")

    allowed_tools = fm.get("allowed-tools")
    if allowed_tools is not None and not isinstance(allowed_tools, str):
        errors.append(
            f"{skill_md}: `allowed-tools` must be a space-separated string, "
            f"got {type(allowed_tools).__name__}"
        )

    return errors


def main() -> int:
    skills_root = REPO_ROOT / "plugins" / "asta-tools" / "skills"
    errors: list[str] = []
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        errors.extend(validate(skill_md))
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n{len(errors)} validation error(s)", file=sys.stderr)
        return 1
    print(f"All {len(list(skills_root.glob('*/SKILL.md')))} SKILL.md files valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
