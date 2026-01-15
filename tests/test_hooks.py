"""Tests for PermissionRequest hooks."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_hooks_json_valid():
    """Verify hooks.json is valid JSON with correct structure."""
    hooks_path = ROOT / "hooks" / "hooks.json"
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
        ROOT / "hooks" / "approve-asta-files.sh",
        ROOT / "hooks" / "approve-asta-bash.sh",
    ]

    for script in scripts:
        assert script.exists(), f"{script.name} not found"
        assert os.access(script, os.X_OK), f"{script.name} is not executable"
        print(f"✓ {script.name} exists and is executable")


def test_approve_asta_files_allows_asta_path():
    """Test approve-asta-files.sh approves ~/.asta/ paths."""
    script = ROOT / "hooks" / "approve-asta-files.sh"
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
    script = ROOT / "hooks" / "approve-asta-files.sh"

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


def test_approve_asta_bash_allows_jq():
    """Test approve-asta-bash.sh approves jq commands on ~/.asta/."""
    script = ROOT / "hooks" / "approve-asta-bash.sh"

    input_json = json.dumps(
        {"tool_input": {"command": "jq '.results' ~/.asta/widgets/test.json"}}
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
    print("✓ approve-asta-bash.sh approves jq on ~/.asta/")


def test_approve_asta_bash_asks_for_other_commands():
    """Test approve-asta-bash.sh returns empty for non-jq commands."""
    script = ROOT / "hooks" / "approve-asta-bash.sh"

    input_json = json.dumps({"tool_input": {"command": "rm -rf /important"}})
    result = subprocess.run(
        ["bash", str(script)],
        input=input_json,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {}, "Expected empty JSON for non-jq commands"
    print("✓ approve-asta-bash.sh returns empty for other commands")


if __name__ == "__main__":
    test_hooks_json_valid()
    test_hook_scripts_executable()
    test_approve_asta_files_allows_asta_path()
    test_approve_asta_files_asks_for_other_paths()
    test_approve_asta_bash_allows_jq()
    test_approve_asta_bash_asks_for_other_commands()
    print("\n✓ All hook tests passed!")
