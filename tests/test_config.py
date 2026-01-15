"""Tests for plugin configuration files."""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_mcp_json_valid():
    """Verify .mcp.json is valid JSON."""
    mcp_path = ROOT / ".mcp.json"
    assert mcp_path.exists(), ".mcp.json not found"

    with open(mcp_path) as f:
        config = json.load(f)

    assert "mcpServers" in config, "Expected 'mcpServers' key"
    print(f"✓ .mcp.json is valid ({len(config['mcpServers'])} servers)")


def test_plugin_json_valid():
    """Verify plugin.json is valid JSON if it exists."""
    plugin_path = ROOT / ".claude-plugin" / "plugin.json"
    if not plugin_path.exists():
        print("⊘ plugin.json not found (skipped)")
        return

    with open(plugin_path) as f:
        config = json.load(f)

    assert "name" in config, "Expected 'name' key in plugin.json"
    print(f"✓ plugin.json is valid (plugin: {config['name']})")


if __name__ == "__main__":
    test_mcp_json_valid()
    test_plugin_json_valid()
    print("\nAll tests passed!")
