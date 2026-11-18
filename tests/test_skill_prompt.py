"""Regression tests for the model-visible plugin skill check."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check-skill-prompt.py"
CAPTURE = CHECKER.with_name("capture-claude-skill-prompt.py")
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


def run_check(tmp_path, target, prompt, skill_source, *, extra_plugins=()):
    checker = tmp_path / "scripts" / CHECKER.name
    checker.parent.mkdir()
    shutil.copyfile(CHECKER, checker)
    source = "./plugins/workflows"
    marketplace = tmp_path / ".claude-plugin" / "marketplace.json"
    marketplace.parent.mkdir()
    marketplace.write_text(
        json.dumps(
            {"plugins": [{"name": "asta-flows", "source": source}, *extra_plugins]}
        )
    )
    if skill_source is not None:
        skill = tmp_path / source / "skills" / "run-workflow" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(skill_source.encode("utf-8"))

    prompt_json = tmp_path / "prompt.json"
    prompt_json.write_text(prompt if isinstance(prompt, str) else json.dumps(prompt))
    return subprocess.run(
        [sys.executable, checker, target, prompt_json], capture_output=True, text=True
    )


def check_result(result, error):
    if error:
        assert result.returncode == 1
        assert error in result.stderr
        assert "Traceback" not in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert "all 1 skills shown with full descriptions" in result.stdout


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
        ([skills_message()], None, "asta-flows: no SKILL.md files found"),
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
    check_result(run_check(tmp_path, "codex", prompt, skill_source), error)


def test_check_rejects_empty_plugin_with_other_skills(tmp_path):
    source = "./plugins/asta-dev"
    (tmp_path / source / "skills").mkdir(parents=True)
    result = run_check(
        tmp_path,
        "codex",
        [skills_message()],
        SKILL_SOURCE,
        extra_plugins=({"name": "asta-dev", "source": source},),
    )
    check_result(result, "asta-dev: no SKILL.md files found")


@pytest.mark.parametrize(
    ("entry", "role", "error"),
    [
        (
            "- asta-flows:run-workflow: Full &lt;description&gt; & examples",
            "system",
            None,
        ),
        ("- asta-flows:run-workflow: Full &lt;description&gt; & examples", None, None),
        ("- asta-flows:run-workflow", "system", "empty description"),
        ("- asta-flows:run-workflow: Full", "system", "description mismatch"),
        ("- unrelated", "system", "not in the Claude Code skills prompt"),
        (
            "- asta-flows:run-workflow: Full &lt;description&gt; & examples",
            "user",
            "expected one non-empty Claude Code skills list",
        ),
    ],
)
def test_check_claude_skill_prompt(tmp_path, entry, role, error):
    heading = "The following skills are available for use with the Skill tool:"
    text = {"type": "text", "text": f"{heading}\n\n{entry}\n\nEnd"}
    if role is None:
        prompt = {"system": [text], "messages": []}
    else:
        prompt = {"messages": [{"role": role, "content": [text]}]}
    skill_source = SKILL_SOURCE.replace(
        "Full description", "|\n  Full <description>\n  & examples"
    )
    check_result(run_check(tmp_path, "claude-code", prompt, skill_source), error)


@pytest.mark.parametrize(
    ("separator", "error"),
    [
        ("\n", "duplicate entry in the Claude Code skills prompt"),
        (
            "\n\nThe following skills are available for use with the Skill tool:\n\n",
            "expected one non-empty Claude Code skills list",
        ),
        (
            "\nThe following skills are available for use with the Skill tool:\n\n",
            "expected one non-empty Claude Code skills list",
        ),
    ],
)
def test_duplicate_claude_skills(tmp_path, separator, error):
    heading = "The following skills are available for use with the Skill tool:"
    skill = "- asta-flows:run-workflow: Full description"
    prompt = {
        "system": [{"type": "text", "text": f"{heading}\n\n{skill}{separator}{skill}"}]
    }
    check_result(run_check(tmp_path, "claude-code", prompt, SKILL_SOURCE), error)


def test_capture_claude_main_request(tmp_path, monkeypatch):
    claude = tmp_path / "claude"
    claude.write_text(
        f"#!{sys.executable}\n"
        """\
import http.client
import json
import os
import socket
import sys
from urllib.parse import urlsplit

assert os.environ["DISABLE_AUTOUPDATER"] == "1"
url = urlsplit(os.environ["ANTHROPIC_BASE_URL"])
connection = http.client.HTTPConnection(url.hostname, url.port)
connection.putrequest("POST", "/v1/messages")
connection.endheaders()
response = connection.getresponse()
assert response.status == 411
assert json.load(response)["error"]["message"] == "Content-Length is required"

def post_incomplete(end_body):
    connection.request("POST", "/v1/messages", "{}", {"Content-Length": "3"})
    if end_body:
        connection.sock.shutdown(socket.SHUT_WR)
    response = connection.getresponse()
    return response.status, json.load(response)["error"]["message"]

assert post_incomplete(end_body=True) == (400, "Incomplete Messages request")
assert post_incomplete(end_body=False) == (408, "Timed out reading Messages request")

def post(payload):
    connection.request("POST", "/v1/messages", json.dumps(payload))
    response = connection.getresponse()
    content = response.read()
    assert response.status == 200, content
    return response.headers["Content-Type"], content

probe = sys.argv[-1]
aux = {"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": probe}]}
content_type, content = post(aux)
assert content_type == "application/json"
assert json.loads(content)["stop_reason"] == "end_turn"

main = {**aux, "stream": True, "tools": [{"name": "Read"}]}
main["messages"] = [{"role": "user", "content": [{"type": "text", "text": probe}]}]
content_type, content = post(main)
assert content_type == "text/event-stream"
assert b"event: message_stop" in content
"""
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    result = subprocess.run(
        [sys.executable, CAPTURE, tmp_path], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["tools"] == [{"name": "Read"}]
