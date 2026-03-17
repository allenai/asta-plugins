"""Configuration management for asta using pyhocon"""

import os
from pathlib import Path
from typing import Any

from pyhocon import ConfigFactory


def get_config_path() -> Path:
    """Get the path to the configuration file.

    Returns:
        Path to the configuration file, either from ASTA_CONFIG_FILE env var
        or the default asta.conf in this module's directory
    """
    config_file = os.environ.get("ASTA_CONFIG_FILE")
    if config_file:
        return Path(config_file)
    return Path(__file__).parent / "asta.conf"


def get_config() -> dict[str, Any]:
    """Load the complete configuration from HOCON file.

    Returns:
        Configuration dictionary with all asta settings (auth, passthrough, etc.)

    Raises:
        FileNotFoundError: If the configuration file doesn't exist
    """
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = ConfigFactory.parse_file(str(config_path))
    return config.as_plain_ordered_dict()


def get_passthrough_config(command_name: str) -> dict[str, Any]:
    """Get configuration for a specific passthrough command.

    Args:
        command_name: Name of the command (e.g., "documents", "experiment")

    Returns:
        Configuration dictionary for the specified command

    Raises:
        KeyError: If the command is not found in configuration
    """
    config = get_config()
    passthrough_config = config.get("passthrough", {})

    if command_name not in passthrough_config:
        raise KeyError(
            f"Command '{command_name}' not found in passthrough configuration"
        )

    return passthrough_config[command_name]


def get_api_config(api_name: str) -> dict[str, Any]:
    """Get configuration for a specific API.

    Args:
        api_name: Name of the API (e.g., "semantic_scholar", "paper_finder")

    Returns:
        Configuration dictionary for the specified API

    Raises:
        KeyError: If the API is not found in configuration
    """
    config = get_config()
    apis_config = config.get("apis", {})

    if api_name not in apis_config:
        raise KeyError(f"API '{api_name}' not found in apis configuration")

    return apis_config[api_name]
