#!/usr/bin/env python3
"""Fail when Codex does not show an asta skill to the model in full.

Reads `codex debug prompt-input` JSON and checks that every
plugins/*/skills/*/SKILL.md appears in the rendered skills list with its
complete frontmatter description. Codex drops or shortens skills silently when
the shared skills prompt budget runs out, so the install alone proves nothing.

Usage: check-codex-skill-prompt.py <prompt-input.json>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_LINE = re.compile(r"^- ([a-z0-9-]+):([a-z0-9-]+): (.*?)(?: \(file: [^)]*\))?$")


def texts(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "text" and isinstance(value, str):
                yield value
            else:
                yield from texts(value)
    elif isinstance(node, list):
        for value in node:
            yield from texts(value)


def squash(text: str) -> str:
    return " ".join(text.split())


def expected_skills() -> dict[str, str]:
    skills = {}
    for skill_md in sorted(REPO_ROOT.glob("plugins/*/skills/*/SKILL.md")):
        raw = skill_md.read_text()
        fm = yaml.safe_load(raw[4 : raw.index("\n---\n", 4)]) or {}
        plugin = skill_md.parents[2].name
        skills[f"{plugin}:{skill_md.parent.name}"] = squash(fm.get("description") or "")
    return skills


def main() -> int:
    prompt = json.loads(Path(sys.argv[1]).read_text())
    rendered = {}
    for text in texts(prompt):
        for line in text.splitlines():
            match = SKILL_LINE.match(line)
            if match:
                rendered[f"{match[1]}:{match[2]}"] = squash(match[3])

    failures = []
    expected = expected_skills()
    for key, want in expected.items():
        got = rendered.get(key)
        if got is None:
            failures.append(f"{key}: not in the Codex skills prompt")
        elif not got:
            failures.append(f"{key}: empty description in the Codex skills prompt")
        elif got != want:
            failures.append(
                f"{key}: description shortened in the Codex skills prompt "
                f"({len(got)} of {len(want)} chars shown)"
            )

    for failure in failures:
        print(f"  ✗ {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"  ✓ codex prompt: all {len(expected)} skills shown with full descriptions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
