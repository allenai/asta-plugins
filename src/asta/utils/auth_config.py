"""
Configuration for authentication settings.
"""

from dataclasses import dataclass

from asta.utils.config import get_config


@dataclass
class AuthSettings:
    """Authentication settings for Asta CLI."""

    # Auth0 (client_id is a public client for device flow)
    auth0_domain: str
    auth0_client_id: str
    auth0_audience: str

    # Gateway
    gateway_url: str


def get_auth_settings() -> AuthSettings:
    """
    Get authentication settings from configuration file.
    Returns:
        Authentication settings loaded from config file with env var overrides
    """
    # Load from config file
    config = get_config()["auth"]

    # Apply environment variable overrides
    return AuthSettings(
        auth0_domain=config["auth0_domain"],
        auth0_client_id=config["auth0_client_id"],
        auth0_audience=config["auth0_audience"],
        gateway_url=config["gateway_url"],
    )
