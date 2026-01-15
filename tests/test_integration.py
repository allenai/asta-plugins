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
    assert (ROOT / "commands").is_dir()
    assert (ROOT / "hooks").is_dir()
    assert (ROOT / "servers" / "paper-finder" / "find_papers.py").exists()
    print("✓ Plugin structure is correct")


def test_plugin_manifest():
    """Verify plugin.json is valid and has required fields."""
    manifest_path = ROOT / ".claude-plugin" / "plugin.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    assert "name" in manifest
    assert "version" in manifest
    assert "mcpServers" in manifest
    print(f"✓ Plugin manifest valid: {manifest['name']} v{manifest['version']}")


def test_mcp_config_valid():
    """Verify .mcp.json has expected servers."""
    mcp_path = ROOT / ".mcp.json"
    with open(mcp_path) as f:
        config = json.load(f)

    # Check asta server exists
    assert "asta" in config["mcpServers"], "Expected 'asta' server in .mcp.json"
    assert config["mcpServers"]["asta"]["type"] == "http"
    print("✓ MCP config is valid")


def test_paper_finder_cli_help():
    """Verify paper-finder CLI works."""
    result = subprocess.run(
        [
            "uv",
            "run",
            str(ROOT / "servers" / "paper-finder" / "find_papers.py"),
            "--help",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    assert result.returncode == 0, f"CLI --help failed: {result.stderr}"
    assert "query" in result.stdout.lower()
    print("✓ Paper-finder CLI works")


if __name__ == "__main__":
    test_plugin_structure()
    test_plugin_manifest()
    test_mcp_config_valid()
    test_paper_finder_cli_help()
    print("\n✓ All integration tests passed!")
