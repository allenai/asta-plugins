"""Tests for plugin configuration files."""

import json
from pathlib import Path

import pytest

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


class TestHoconConfig:
    """Test HOCON configuration module."""

    def test_get_config(self):
        """Test loading the full configuration."""
        from asta.utils.config import get_config

        config = get_config()

        assert isinstance(config, dict)
        assert "passthrough" in config
        assert isinstance(config["passthrough"], dict)

    def test_get_passthrough_config_documents(self):
        """Test loading documents passthrough configuration."""
        from asta.utils.config import get_passthrough_config
        from asta.utils.passthrough import validate_semver

        config = get_passthrough_config("documents")

        # Verify required fields
        assert config["tool_name"] == "asta-documents"
        assert config["command_name"] == "documents"
        assert config["friendly_name"] == "asta-documents"
        assert "install_type" in config
        assert "install_source" in config
        assert "minimum_version" in config
        assert "docstring" in config

        # Verify types
        assert isinstance(config["tool_name"], str)
        assert isinstance(config["install_type"], str)
        assert isinstance(config["minimum_version"], str)
        assert isinstance(config["install_source"], str)

        # Verify install_type is valid
        assert config["install_type"] in ("pypi", "git", "local"), (
            f"install_type '{config['install_type']}' must be one of: pypi, git, local"
        )

        # Verify minimum_version is in valid x.y.z format
        assert validate_semver(config["minimum_version"]), (
            f"minimum_version '{config['minimum_version']}' must be in x.y.z format"
        )

    def test_get_passthrough_config_experiment(self):
        """Test loading experiment passthrough configuration."""
        from asta.utils.config import get_passthrough_config
        from asta.utils.passthrough import validate_semver

        config = get_passthrough_config("experiment")

        # Verify required fields
        assert config["tool_name"] == "panda"
        assert config["command_name"] == "experiment"
        assert config["friendly_name"] == "panda"
        assert "install_type" in config
        assert "install_source" in config
        assert "minimum_version" in config
        assert "docstring" in config

        # Verify types
        assert isinstance(config["tool_name"], str)
        assert isinstance(config["install_type"], str)
        assert isinstance(config["minimum_version"], str)
        assert isinstance(config["install_source"], str)

        # Verify install_type is valid
        assert config["install_type"] in ("pypi", "git", "local"), (
            f"install_type '{config['install_type']}' must be one of: pypi, git, local"
        )

        # Verify minimum_version is in valid x.y.z format
        assert validate_semver(config["minimum_version"]), (
            f"minimum_version '{config['minimum_version']}' must be in x.y.z format"
        )

    def test_get_passthrough_config_invalid_command(self):
        """Test that invalid command names raise KeyError."""
        from asta.utils.config import get_passthrough_config

        with pytest.raises(KeyError, match="not found in passthrough configuration"):
            get_passthrough_config("nonexistent_command")

    def test_config_has_all_passthrough_commands(self):
        """Test that config includes all expected passthrough commands."""
        from asta.utils.config import get_config

        config = get_config()
        passthrough = config["passthrough"]

        # Should have documents and experiment
        assert "documents" in passthrough
        assert "experiment" in passthrough

    def test_passthrough_conf_file_exists(self):
        """Test that the passthrough.conf file exists."""
        conf_path = ROOT / "src" / "asta" / "utils" / "passthrough.conf"
        assert conf_path.exists(), f"passthrough.conf not found at {conf_path}"


if __name__ == "__main__":
    test_plugin_json_valid()
    pytest.main([__file__, "-v"])
    print("\n✓ All config tests passed!")
