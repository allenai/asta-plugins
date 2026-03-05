"""Configuration management for asta using pyhocon"""

from pathlib import Path
from typing import Any

from pyhocon import ConfigFactory


def get_config() -> dict[str, Any]:
    """Load the passthrough configuration from HOCON file.

    Returns:
        Configuration dictionary with passthrough tool settings
    """
    config_path = Path(__file__).parent / "passthrough.conf"
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
