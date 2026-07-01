"""Integration tests for the plugin.

These tests verify the plugin works end-to-end without requiring Claude Code.
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_plugin_structure():
    """Verify plugins have correct directory structure."""
    assert (ROOT / ".claude-plugin" / "marketplace.json").exists()
    assert (ROOT / "plugins" / "asta-tools" / "skills").is_dir()
    assert (ROOT / "plugins" / "asta-tools" / "hooks").is_dir()
    assert (ROOT / "plugins" / "asta-flows" / "skills").is_dir()
    assert (ROOT / "plugins" / "asta-dev" / "skills").is_dir()
    assert (ROOT / "src" / "asta").is_dir()
    # Check key CLI modules exist
    assert (ROOT / "src" / "asta" / "cli.py").exists()
    assert (ROOT / "src" / "asta" / "literature").is_dir()
    assert (ROOT / "src" / "asta" / "papers").is_dir()
    print("✓ Plugin structure is correct")


def test_marketplace_has_plugins():
    """Verify marketplace.json lists all plugins."""
    with open(ROOT / ".claude-plugin" / "marketplace.json") as f:
        marketplace = json.load(f)
    names = {p["name"] for p in marketplace["plugins"]}
    assert {"asta-tools", "asta-flows", "asta-dev"} <= names
    print("✓ Marketplace lists asta-tools, asta-flows, and asta-dev plugins")


def test_marketplace_sources_resolve():
    """Every marketplace `source` must resolve to a real plugin dir with skills.

    marketplace.json is the single metadata source consumed by `npx plugins
    add` and native Claude/Codex; a typo'd or stale `source` would make a
    listed plugin uninstallable, which discovery alone wouldn't catch.
    """
    with open(ROOT / ".claude-plugin" / "marketplace.json") as f:
        marketplace = json.load(f)
    for entry in marketplace["plugins"]:
        source = (ROOT / entry["source"]).resolve()
        assert source.is_dir(), f"{entry['name']}: source {entry['source']} missing"
        assert (source / "skills").is_dir(), (
            f"{entry['name']}: source {entry['source']} has no skills/ "
            "(installers wouldn't recognise it as a plugin)"
        )
    print("✓ Marketplace sources resolve to plugin dirs")


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
    test_marketplace_sources_resolve()
    test_asta_cli_installed()
    test_asta_cli_help()
    print("\n✓ All integration tests passed!")
