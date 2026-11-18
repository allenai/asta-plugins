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


def message(role, text):
    return {
        "type": "message",
        "role": role,
        "content": [{"type": "input_text", "text": text}],
    }


def skills_message(text=SKILLS_BLOCK):
    return message("developer", text)


@pytest.mark.parametrize(
    ("prompt", "has_inventory", "error"),
    [
        ([skills_message()], True, None),
        (
            [
                skills_message(SKILLS_BLOCK.replace(SKILL_ENTRY, "")),
                message("user", f"# AGENTS.md instructions\n{SKILL_ENTRY}"),
            ],
            True,
            "asta-flows:run-workflow: not in the Codex skills prompt",
        ),
        (
            [
                skills_message(
                    SKILLS_BLOCK.replace("Full description", "Fake description")
                )
            ],
            True,
            "expected 'Full description'\n    rendered 'Fake description'",
        ),
        (
            [message("user", SKILLS_BLOCK)],
            True,
            "expected one Codex skills instructions block, found 0",
        ),
        (
            [skills_message(), skills_message()],
            True,
            "expected one Codex skills instructions block, found 2",
        ),
        ([skills_message()], False, "no expected skills found"),
    ],
    ids=[
        "full",
        "masked-by-agents-md",
        "replaced",
        "missing-block",
        "duplicate-block",
        "empty-inventory",
    ],
)
def test_check_codex_skill_prompt(tmp_path, prompt, has_inventory, error):
    checker = tmp_path / "scripts" / CHECKER.name
    checker.parent.mkdir()
    shutil.copyfile(CHECKER, checker)
    if has_inventory:
        skill = (
            tmp_path / "plugins" / "asta-flows" / "skills" / "run-workflow" / "SKILL.md"
        )
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: run-workflow\ndescription: Full description\n---\n"
        )

    prompt_json = tmp_path / "prompt.json"
    prompt_json.write_text(json.dumps(prompt))
    result = subprocess.run(
        [sys.executable, checker, prompt_json], capture_output=True, text=True
    )

    if error:
        assert result.returncode == 1
        assert error in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert "all 1 skills shown with full descriptions" in result.stdout
