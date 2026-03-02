"""Integration tests for the plugin.

These tests verify the plugin works end-to-end without requiring Claude Code.
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_plugin_structure():
    """Verify plugin has correct directory structure."""
    assert (ROOT / ".claude-plugin" / "plugin.json").exists()
    assert (ROOT / ".mcp.json").exists()
    assert (ROOT / "skills").is_dir()
    assert (ROOT / "hooks").is_dir()
    assert (ROOT / "src" / "asta").is_dir()
    # Check key CLI modules exist
    assert (ROOT / "src" / "asta" / "cli.py").exists()
    assert (ROOT / "src" / "asta" / "literature").is_dir()
    assert (ROOT / "src" / "asta" / "papers").is_dir()
    print("✓ Plugin structure is correct")


def test_plugin_manifest():
    """Verify plugin.json is valid and has required fields."""
    manifest_path = ROOT / ".claude-plugin" / "plugin.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    assert "name" in manifest
    assert "version" in manifest
    print(f"✓ Plugin manifest valid: {manifest['name']} v{manifest['version']}")


def test_asta_cli_installed():
    """Verify asta CLI can be invoked."""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "asta.cli", "--version"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    assert result.returncode == 0, f"asta --version failed: {result.stderr}"
    print("✓ Asta CLI is installed and working")


def test_asta_cli_help():
    """Verify asta CLI help commands work."""
    # Test main help
    result = subprocess.run(
        ["uv", "run", "python", "-m", "asta.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0
    assert "Science literature research tools" in result.stdout

    # Test literature subcommand help
    result = subprocess.run(
        ["uv", "run", "python", "-m", "asta.cli", "literature", "--help"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0
    assert "Literature research commands" in result.stdout
    assert "find" in result.stdout

    # Test find command help
    result = subprocess.run(
        ["uv", "run", "python", "-m", "asta.cli", "literature", "find", "--help"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0
    assert "Find papers matching QUERY" in result.stdout
    assert "--timeout" in result.stdout
    assert "-o" in result.stdout or "--output" in result.stdout

    print("✓ Asta CLI help commands work")


if __name__ == "__main__":
    test_plugin_structure()
    test_plugin_manifest()
    test_asta_cli_installed()
    test_asta_cli_help()
    print("\n✓ All integration tests passed!")
