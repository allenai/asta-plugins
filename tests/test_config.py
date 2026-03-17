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

    def test_asta_conf_file_exists(self):
        """Test that the asta.conf file exists."""
        conf_path = ROOT / "src" / "asta" / "utils" / "asta.conf"
        assert conf_path.exists(), f"asta.conf not found at {conf_path}"

    def test_get_auth_config(self):
        """Test loading auth configuration."""
        from asta.utils.config import get_config

        config = get_config()["auth"]

        # Verify required fields
        assert "auth0_domain" in config
        assert "auth0_client_id" in config
        assert "auth0_audience" in config
        assert "gateway_url" in config

        # Verify types
        assert isinstance(config["auth0_domain"], str)
        assert isinstance(config["auth0_client_id"], str)
        assert isinstance(config["auth0_audience"], str)
        assert isinstance(config["gateway_url"], str)

    def test_get_auth_settings(self):
        """Test loading auth settings through auth_config module."""
        from asta.utils.auth_config import get_auth_settings

        settings = get_auth_settings()

        # Verify settings has expected attributes
        assert hasattr(settings, "auth0_domain")
        assert hasattr(settings, "auth0_client_id")
        assert hasattr(settings, "auth0_audience")
        assert hasattr(settings, "gateway_url")

        # Verify values are strings
        assert isinstance(settings.auth0_domain, str)
        assert isinstance(settings.auth0_client_id, str)
        assert isinstance(settings.auth0_audience, str)
        assert isinstance(settings.gateway_url, str)

    def test_get_api_config_semantic_scholar(self):
        """Test loading semantic_scholar API configuration."""
        from asta.utils.config import get_api_config

        config = get_api_config("semantic_scholar")

        # Verify required fields
        assert "base_url" in config
        assert isinstance(config["base_url"], str)
        assert config["base_url"].startswith("https://")

    def test_get_api_config_paper_finder(self):
        """Test loading paper_finder API configuration."""
        from asta.utils.config import get_api_config

        config = get_api_config("paper_finder")

        # Verify required fields
        assert "base_url" in config
        assert isinstance(config["base_url"], str)
        assert config["base_url"].startswith("https://")

    def test_get_api_config_invalid_api(self):
        """Test that invalid API names raise KeyError."""
        from asta.utils.config import get_api_config

        with pytest.raises(KeyError, match="not found in apis configuration"):
            get_api_config("nonexistent_api")

    def test_config_has_apis_section(self):
        """Test that config includes apis section."""
        from asta.utils.config import get_config

        config = get_config()
        assert "apis" in config
        apis = config["apis"]

        # Should have semantic_scholar and paper_finder
        assert "semantic_scholar" in apis
        assert "paper_finder" in apis

    def test_custom_config_file_path(self, tmp_path, monkeypatch):
        """Test that ASTA_CONFIG_FILE environment variable works."""
        from asta.utils.config import get_config_path

        # Create a custom config file
        custom_config = tmp_path / "custom.conf"
        custom_config.write_text(
            """
            auth {
              auth0_domain = "custom.domain.com"
              auth0_client_id = "custom_client_id"
              auth0_audience = "https://custom.audience"
              gateway_url = "https://custom.gateway"
            }
            passthrough {
              documents {
                tool_name = "asta-documents"
                install_type = "pypi"
                install_source = "asta-resource-repository"
                minimum_version = "0.3.0"
                command_name = "documents"
                friendly_name = "asta-documents"
                docstring = "Test"
              }
            }
            """
        )

        # Set environment variable
        monkeypatch.setenv("ASTA_CONFIG_FILE", str(custom_config))

        # Verify config path is set correctly
        assert get_config_path() == custom_config

        # Verify we can load the custom config
        from asta.utils.config import get_config

        config = get_config()
        assert config["auth"]["auth0_domain"] == "custom.domain.com"


if __name__ == "__main__":
    test_plugin_json_valid()
    pytest.main([__file__, "-v"])
    print("\n✓ All config tests passed!")
