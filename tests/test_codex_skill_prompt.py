"""Regression tests for the Codex plugin install check."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = (
    Path(__file__).resolve().parents[1] / "scripts" / "check-codex-skill-prompt.py"
)
SKILL_ENTRY = (
    "- asta-flows:run-workflow: Full description (file: r0/run-workflow/SKILL.md)"
)
SKILLS_BLOCK = f"<skills_instructions>\n### Available skills\n{SKILL_ENTRY}\n</skills_instructions>"
SKILL_SOURCE = "---\nname: run-workflow\ndescription: Full description\n---\n"


def message(role, text):
    return {
        "type": "message",
        "role": role,
        "content": [{"type": "input_text", "text": text}],
    }


def skills_message(text=SKILLS_BLOCK):
    return message("developer", text)


@pytest.mark.parametrize(
    ("prompt", "skill_source", "error"),
    [
        ([skills_message()], SKILL_SOURCE, None),
        (
            [
                skills_message(SKILLS_BLOCK.replace(SKILL_ENTRY, "")),
                message("user", f"# AGENTS.md instructions\n{SKILL_ENTRY}"),
            ],
            SKILL_SOURCE,
            "asta-flows:run-workflow: not in the Codex skills prompt",
        ),
        (
            [
                skills_message(
                    SKILLS_BLOCK.replace("Full description", "Fake description")
                )
            ],
            SKILL_SOURCE,
            "expected 'Full description'\n    rendered 'Fake description'",
        ),
        (
            [skills_message(SKILLS_BLOCK.replace("Full description", "Full…"))],
            SKILL_SOURCE,
            "expected 'Full description'\n    rendered 'Full…'",
        ),
        (
            [skills_message(SKILLS_BLOCK.replace("Full description ", ""))],
            SKILL_SOURCE,
            "asta-flows:run-workflow: empty description in the Codex skills prompt",
        ),
        (
            [
                skills_message(
                    SKILLS_BLOCK.replace(SKILL_ENTRY, f"{SKILL_ENTRY}\n{SKILL_ENTRY}")
                )
            ],
            SKILL_SOURCE,
            "asta-flows:run-workflow: duplicate entry in the Codex skills prompt",
        ),
        (
            [message("user", SKILLS_BLOCK)],
            SKILL_SOURCE,
            "expected one Codex skills instructions block, found 0",
        ),
        (
            [skills_message(), skills_message()],
            SKILL_SOURCE,
            "expected one Codex skills instructions block, found 2",
        ),
        ([skills_message()], None, "no expected skills found"),
        (
            [skills_message(SKILLS_BLOCK.replace("r0/", "/tmp/checkout)/"))],
            "---\r\nname: run-workflow\r\ndescription: >\r\n  Full\r\n  description\r\n---",
            None,
        ),
        (
            [
                skills_message(
                    SKILLS_BLOCK.replace(
                        "Full description", "Read (file: /docs/examples/SKILL.md)"
                    )
                )
            ],
            SKILL_SOURCE.replace(
                "Full description", "'Read (file: /docs/examples/SKILL.md)'"
            ),
            None,
        ),
        (
            [
                skills_message(
                    SKILLS_BLOCK.replace(
                        "(file: r0/run-workflow/SKILL.md)", "(file: /docs/config)"
                    )
                )
            ],
            SKILL_SOURCE,
            "asta-flows:run-workflow: missing or invalid SKILL.md path suffix",
        ),
        (
            [skills_message(SKILLS_BLOCK.replace("r0/run-workflow/", "r0/other/"))],
            SKILL_SOURCE,
            "asta-flows:run-workflow: missing or invalid SKILL.md path suffix",
        ),
        (
            [skills_message()],
            SKILL_SOURCE.removeprefix("---\n"),
            "SKILL.md: missing or unterminated YAML frontmatter",
        ),
        (
            [skills_message()],
            SKILL_SOURCE.replace("Full description", "[unclosed"),
            "SKILL.md: invalid YAML frontmatter",
        ),
        (
            [skills_message()],
            SKILL_SOURCE.replace("Full description", "42"),
            "SKILL.md: description must be a non-empty string",
        ),
        (
            [skills_message()],
            SKILL_SOURCE.replace("description: Full description\n", ""),
            "SKILL.md: description must be a non-empty string",
        ),
        ("warning: invalid response", SKILL_SOURCE, "invalid Codex prompt JSON"),
        (
            [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{}, {"type": "input_text"}],
                }
            ],
            SKILL_SOURCE,
            "expected text in Codex developer message content",
        ),
    ],
    ids=[
        "full",
        "masked-by-agents-md",
        "replaced",
        "shortened",
        "empty-description",
        "duplicate-entry",
        "missing-block",
        "duplicate-block",
        "empty-inventory",
        "folded-crlf-frontmatter-and-path-with-parenthesis",
        "file-marker-in-description",
        "missing-file-suffix-with-file-marker-in-description",
        "file-suffix-points-to-other-skill",
        "missing-frontmatter",
        "invalid-yaml",
        "non-string-description",
        "missing-description",
        "invalid-json",
        "invalid-prompt-shape",
    ],
)
def test_check_codex_skill_prompt(tmp_path, prompt, skill_source, error):
    checker = tmp_path / "scripts" / CHECKER.name
    checker.parent.mkdir()
    shutil.copyfile(CHECKER, checker)
    if skill_source is not None:
        skill = (
            tmp_path / "plugins" / "asta-flows" / "skills" / "run-workflow" / "SKILL.md"
        )
        skill.parent.mkdir(parents=True)
        skill.write_bytes(skill_source.encode("utf-8"))

    prompt_json = tmp_path / "prompt.json"
    prompt_json.write_text(prompt if isinstance(prompt, str) else json.dumps(prompt))
    result = subprocess.run(
        [sys.executable, checker, prompt_json], capture_output=True, text=True
    )

    if error:
        assert result.returncode == 1
        assert error in result.stderr
        assert "Traceback" not in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert "all 1 skills shown with full descriptions" in result.stdout
