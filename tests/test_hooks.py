"""Tests for PermissionRequest hooks."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
HOOKS = ROOT / "plugins" / "asta-preview" / "hooks"


def test_hooks_json_valid():
    """Verify hooks.json is valid JSON with correct structure."""
    hooks_path = HOOKS / "hooks.json"
    assert hooks_path.exists(), "hooks.json not found"

    with open(hooks_path) as f:
        config = json.load(f)

    assert "hooks" in config, "Expected 'hooks' key"
    hooks = config["hooks"]
    assert "PermissionRequest" in hooks, "Expected 'PermissionRequest' hooks"
    print(f"✓ hooks.json is valid ({len(hooks)} event types)")


def test_hook_scripts_executable():
    """Verify hook scripts exist and are executable."""
    scripts = [
        HOOKS / "approve-asta-files.sh",
        HOOKS / "approve-asta-bash.sh",
        HOOKS / "approve-bd-bash.sh",
    ]

    for script in scripts:
        assert script.exists(), f"{script.name} not found"
        assert os.access(script, os.X_OK), f"{script.name} is not executable"
        print(f"✓ {script.name} exists and is executable")


def test_approve_asta_files_allows_asta_path():
    """Test approve-asta-files.sh approves ~/.asta/ paths."""
    script = HOOKS / "approve-asta-files.sh"
    home = os.environ.get("HOME", "/home/user")

    # Test with absolute path
    input_json = json.dumps(
        {"tool_input": {"file_path": f"{home}/.asta/reports/test.md"}}
    )
    result = subprocess.run(
        ["bash", str(script)],
        input=input_json,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "hookSpecificOutput" in output
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    print("✓ approve-asta-files.sh approves ~/.asta/ paths")


def test_approve_asta_files_asks_for_other_paths():
    """Test approve-asta-files.sh returns empty for non-asta paths."""
    script = HOOKS / "approve-asta-files.sh"

    input_json = json.dumps({"tool_input": {"file_path": "/tmp/other/file.md"}})
    result = subprocess.run(
        ["bash", str(script)],
        input=input_json,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {}, "Expected empty JSON for non-asta paths"
    print("✓ approve-asta-files.sh returns empty for other paths")


def test_approve_asta_files_allows_command_on_asta_path():
    """Test approve-asta-files.sh approves Bash commands targeting ~/.asta/."""
    script = HOOKS / "approve-asta-files.sh"

    for cmd in [
        "jq '.results' ~/.asta/widgets/test.json",
        "cat ~/.asta/reports/test.md | jq .",
        "rm ~/.asta/tmp/scratch.json",
    ]:
        input_json = json.dumps({"tool_input": {"command": cmd}})
        result = subprocess.run(
            ["bash", str(script)],
            input=input_json,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "hookSpecificOutput" in output, f"no decision for: {cmd}"
        assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow", (
            f"not allowed: {cmd}"
        )
    print("✓ approve-asta-files.sh approves commands on ~/.asta/")


def test_approve_asta_files_allows_cwd_asta_path():
    """Test approve-asta-files.sh approves CWD-relative .asta/ file paths."""
    script = HOOKS / "approve-asta-files.sh"

    for file_path in [
        ".asta/notes.md",
        "./.asta/notes.md",
        ".asta/sub/dir/file.json",
    ]:
        input_json = json.dumps({"tool_input": {"file_path": file_path}})
        result = subprocess.run(
            ["bash", str(script)],
            input=input_json,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "hookSpecificOutput" in output, f"no decision for: {file_path}"
        assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow", (
            f"not allowed: {file_path}"
        )
    print("✓ approve-asta-files.sh approves CWD-relative .asta/ paths")


def test_approve_asta_files_allows_command_on_cwd_asta_path():
    """Test approve-asta-files.sh approves Bash commands targeting CWD .asta/."""
    script = HOOKS / "approve-asta-files.sh"

    for cmd in [
        "cat .asta/notes.md",
        "ls ./.asta/",
        "echo hi > .asta/out.txt",
        ".asta/bin/runme",
    ]:
        input_json = json.dumps({"tool_input": {"command": cmd}})
        result = subprocess.run(
            ["bash", str(script)],
            input=input_json,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "hookSpecificOutput" in output, f"no decision for: {cmd}"
        assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow", (
            f"not allowed: {cmd}"
        )
    print("✓ approve-asta-files.sh approves commands on CWD-relative .asta/")


def test_approve_asta_files_rejects_arbitrary_dir_asta():
    """Test approve-asta-files.sh rejects .asta/ under arbitrary (non-HOME, non-CWD) dirs."""
    script = HOOKS / "approve-asta-files.sh"

    for tool_input in [
        {"file_path": "/tmp/proj/.asta/foo"},
        {"file_path": "/var/lib/.asta/x"},
        {"command": "cat /tmp/proj/.asta/foo"},
        {"command": "ls /opt/random/.asta/"},
    ]:
        input_json = json.dumps({"tool_input": tool_input})
        result = subprocess.run(
            ["bash", str(script)],
            input=input_json,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}, f"expected empty JSON for: {tool_input}"
    print("✓ approve-asta-files.sh rejects arbitrary-dir .asta/")


def test_approve_asta_files_does_not_match_asta_suffix_lookalike():
    """Paths/commands like `foo.asta/` should not be treated as .asta/ dirs."""
    script = HOOKS / "approve-asta-files.sh"

    for tool_input in [
        {"file_path": "foo.asta/bar"},
        {"command": "cat foo.asta/bar"},
    ]:
        input_json = json.dumps({"tool_input": tool_input})
        result = subprocess.run(
            ["bash", str(script)],
            input=input_json,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}, f"expected empty JSON for: {tool_input}"
    print("✓ approve-asta-files.sh does not match .asta-suffix lookalikes")


def test_approve_asta_bash_allows_asta_cli():
    """Test approve-asta-bash.sh approves `asta` CLI invocations."""
    script = HOOKS / "approve-asta-bash.sh"

    input_json = json.dumps({"tool_input": {"command": "asta papers search foo"}})
    result = subprocess.run(
        ["bash", str(script)],
        input=input_json,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "hookSpecificOutput" in output
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    print("✓ approve-asta-bash.sh approves `asta` CLI")


def test_approve_asta_bash_asks_for_other_commands():
    """Test approve-asta-bash.sh returns empty for non-asta commands."""
    script = HOOKS / "approve-asta-bash.sh"

    for cmd in [
        "rm -rf /important",
        "jq '.results' ~/.asta/widgets/test.json",
        "astar foo",
    ]:
        input_json = json.dumps({"tool_input": {"command": cmd}})
        result = subprocess.run(
            ["bash", str(script)],
            input=input_json,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}, f"expected empty JSON for: {cmd}"
    print("✓ approve-asta-bash.sh returns empty for other commands")


def test_approve_bd_bash_allows_bd():
    """Test approve-bd-bash.sh approves bd (beads) CLI commands."""
    script = HOOKS / "approve-bd-bash.sh"

    for cmd in [
        "bd list",
        "bd show abc-123 --json",
        "bd create --type=task --title='x'",
        "bd dep add a b",
    ]:
        input_json = json.dumps({"tool_input": {"command": cmd}})
        result = subprocess.run(
            ["bash", str(script)],
            input=input_json,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "hookSpecificOutput" in output, f"no decision for: {cmd}"
        assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow", (
            f"not allowed: {cmd}"
        )
    print("✓ approve-bd-bash.sh approves bd commands")


def test_approve_bd_bash_does_not_match_bd_prefix_lookalike():
    """`bdiff` and similar should not be auto-approved by the bd hook."""
    script = HOOKS / "approve-bd-bash.sh"

    input_json = json.dumps({"tool_input": {"command": "bdiff a b"}})
    result = subprocess.run(
        ["bash", str(script)],
        input=input_json,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {}, "Expected empty JSON for bd-prefix lookalike"
    print("✓ approve-bd-bash.sh does not match bd-prefix lookalikes")


if __name__ == "__main__":
    test_hooks_json_valid()
    test_hook_scripts_executable()
    test_approve_asta_files_allows_asta_path()
    test_approve_asta_files_asks_for_other_paths()
    test_approve_asta_files_allows_command_on_asta_path()
    test_approve_asta_files_allows_cwd_asta_path()
    test_approve_asta_files_allows_command_on_cwd_asta_path()
    test_approve_asta_files_rejects_arbitrary_dir_asta()
    test_approve_asta_files_does_not_match_asta_suffix_lookalike()
    test_approve_asta_bash_allows_asta_cli()
    test_approve_asta_bash_asks_for_other_commands()
    test_approve_bd_bash_allows_bd()
    test_approve_bd_bash_does_not_match_bd_prefix_lookalike()
    print("\n✓ All hook tests passed!")
