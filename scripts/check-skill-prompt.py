#!/usr/bin/env python3
"""Verify complete Asta skill descriptions in the prompt sent to the model."""

from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import takewhile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTMATTER = re.compile(r"\A---\n(.*?)^---[ \t]*$", re.MULTILINE | re.DOTALL)
SKILL_LINE = re.compile(r"^- ([a-z0-9-]+):([a-z0-9-]+)(?:: ?(.*))?$")
SKILL_ENTRY = re.compile(
    r"(?:(?P<description>.*) )?\(file: (?P<path>(?:/|r[0-9]+/).*)\)"
)


def codex_skill_lines(prompt: object) -> list[str]:
    opening = "<skills_instructions>"
    closing = "</skills_instructions>"
    if not isinstance(prompt, list) or any(
        not isinstance(item, dict) for item in prompt
    ):
        raise ValueError("expected a list of Codex prompt items")

    blocks = []
    for item in prompt:
        if item.get("type") != "message" or item.get("role") != "developer":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            raise ValueError("expected a list of Codex developer message content items")
        for entry in content:
            if not isinstance(entry, dict):
                raise ValueError(
                    "expected an object in Codex developer message content"
                )
            if entry.get("type") != "input_text":
                continue
            value = entry.get("text")
            if not isinstance(value, str):
                raise ValueError("expected text in Codex developer message content")
            if value.startswith(opening + "\n"):
                blocks.append(value.splitlines())
    if len(blocks) != 1:
        raise ValueError(
            f"expected one Codex skills instructions block, found {len(blocks)}"
        )

    lines = blocks[0]
    if lines[-1] != closing or lines.count(opening) != 1 or lines.count(closing) != 1:
        raise ValueError("malformed Codex skills instructions block")
    return lines[1:-1]


def claude_skill_lines(prompt: object) -> list[str]:
    if not isinstance(prompt, dict):
        raise ValueError("expected a Claude Code Messages API request")

    # Claude Code can place its generated skill list in the system prompt or a
    # system-role message. User messages cannot satisfy the check.
    messages = prompt.get("messages", [])
    system = prompt.get("system", [])
    blocks = list(system) if isinstance(system, list) else []
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "system":
                content = message.get("content")
                if isinstance(content, list):
                    blocks.extend(content)

    heading = "The following skills are available for use with the Skill tool:"
    listings = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        value = block.get("text")
        if not isinstance(value, str):
            continue
        lines = iter(value.splitlines())
        for line in lines:
            if line == heading:
                first = next(lines, "")
                if not first:
                    first = next(lines, "")
                entries = [first, *takewhile(lambda row: row.startswith("- "), lines)]
                listings.append(entries if first.startswith("- ") else [])

    if len(listings) != 1 or not listings[0]:
        raise ValueError("expected one non-empty Claude Code skills list")
    return listings[0]


def squash(text: str) -> str:
    return " ".join(text.split())


def expected_skills(source: Path) -> dict[str, str]:
    skills = {}
    for skill_md in sorted(source.glob("plugins/*/skills/*/SKILL.md")):
        path = skill_md.relative_to(source)
        frontmatter = FRONTMATTER.match(skill_md.read_text(encoding="utf-8"))
        if not frontmatter:
            raise ValueError(f"{path}: missing or unterminated YAML frontmatter")
        try:
            metadata = yaml.safe_load(frontmatter[1])
        except yaml.YAMLError as error:
            raise ValueError(f"{path}: invalid YAML frontmatter: {error}") from error
        description = (
            metadata.get("description") if isinstance(metadata, dict) else None
        )
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{path}: description must be a non-empty string")
        plugin = skill_md.parents[2].name
        skills[f"{plugin}:{skill_md.parent.name}"] = squash(description)
    return skills


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("codex", "claude-code"))
    parser.add_argument("prompt", type=Path)
    parser.add_argument("--source", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    is_codex = args.target == "codex"
    harness = "Codex" if is_codex else "Claude Code"
    try:
        expected = expected_skills(args.source)
        if not expected:
            raise ValueError(
                "no expected skills found under plugins/*/skills/*/SKILL.md"
            )
        prompt = json.loads(args.prompt.read_text(encoding="utf-8"))
        lines = codex_skill_lines(prompt) if is_codex else claude_skill_lines(prompt)
    except json.JSONDecodeError as error:
        print(
            f"  ✗ invalid {harness} prompt JSON in {args.prompt}: {error}",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError) as error:
        print(f"  ✗ {error}", file=sys.stderr)
        return 1

    rendered = {}
    failures = []
    for line in lines:
        match = SKILL_LINE.match(line)
        if match:
            key = f"{match[1]}:{match[2]}"
            if key in rendered:
                failures.append(
                    f"{key}: duplicate entry in the {harness} skills prompt"
                )
                continue
            rendered[key] = match[3] or ""

    for key, want in expected.items():
        entry = rendered.get(key)
        if entry is None:
            failures.append(f"{key}: not in the {harness} skills prompt")
            continue
        if is_codex:
            skill = key.split(":", 1)[1]
            match = SKILL_ENTRY.fullmatch(entry)
            if not match or not match["path"].endswith(f"/{skill}/SKILL.md"):
                failures.append(f"{key}: missing or invalid SKILL.md path suffix")
                continue
            entry = match["description"] or ""
        else:
            want = want.replace("<", "&lt;").replace(">", "&gt;")
        got = squash(entry)
        if not got:
            failures.append(f"{key}: empty description in the {harness} skills prompt")
        elif got != want:
            failures.append(
                f"{key}: description mismatch in the {harness} skills prompt\n"
                f"    expected {want!r}\n"
                f"    rendered {got!r}"
            )

    for failure in failures:
        print(f"  ✗ {failure}", file=sys.stderr)
    if failures:
        return 1
    print(
        f"  ✓ {harness} prompt: all {len(expected)} skills shown with full descriptions"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
