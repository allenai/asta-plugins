"""Integration tests for the plugin.

These tests verify the plugin works end-to-end without requiring Claude Code.
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_plugin_structure():
    """Verify plugin has correct directory structure."""
    assert (ROOT / ".claude-plugin" / "marketplace.json").exists()
    assert (ROOT / "plugins" / "asta" / "skills").is_dir()
    assert (ROOT / "plugins" / "asta-preview" / "skills").is_dir()
    assert (ROOT / "skills").is_dir()
    assert (ROOT / "hooks").is_dir()
    assert (ROOT / "src" / "asta").is_dir()
    # Check key CLI modules exist
    assert (ROOT / "src" / "asta" / "cli.py").exists()
    assert (ROOT / "src" / "asta" / "literature").is_dir()
    assert (ROOT / "src" / "asta" / "papers").is_dir()
    print("✓ Plugin structure is correct")


def test_marketplace_has_plugins():
    """Verify marketplace.json lists both plugins."""
    with open(ROOT / ".claude-plugin" / "marketplace.json") as f:
        marketplace = json.load(f)
    names = {p["name"] for p in marketplace["plugins"]}
    assert "asta" in names
    assert "asta-preview" in names
    print("✓ Marketplace lists both plugins")


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

    # Test literature subcommand help
    result = subprocess.run(
        ["uv", "run", "python", "-m", "asta.cli", "literature", "--help"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0

    # Test find command help
    result = subprocess.run(
        ["uv", "run", "python", "-m", "asta.cli", "literature", "find", "--help"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0

    print("✓ Asta CLI help commands work")


if __name__ == "__main__":
    test_plugin_structure()
    test_marketplace_has_plugins()
    test_asta_cli_installed()
    test_asta_cli_help()
    print("\n✓ All integration tests passed!")
