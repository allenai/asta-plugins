"""Tests for plugin configuration files."""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_plugin_json_valid():
    """Verify plugin.json is valid JSON and has required structure."""
    plugin_path = ROOT / ".claude-plugin" / "plugin.json"
    with open(plugin_path) as f:
        config = json.load(f)

    assert "name" in config, "Expected 'name' key"
    assert "version" in config, "Expected 'version' key"

    print(
        f"✓ plugin.json is valid (name={config['name']}, version={config['version']})"
    )


if __name__ == "__main__":
    test_plugin_json_valid()
    print("\n✓ All config tests passed!")
