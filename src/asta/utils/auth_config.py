"""
Configuration for authentication settings.
"""

from dataclasses import dataclass

from asta.utils.config import get_config

DEFAULT_AUTH0_SCOPES = "openid profile email offline_access access:all"


@dataclass
class AuthSettings:
    """Authentication settings for Asta CLI."""

    service_name: str

    # Auth0 (client_id is a public client for PKCE)
    auth0_domain: str
    auth0_client_id: str
    auth0_audience: str
    auth0_scopes: str
    auth0_callback_host: str
    auth0_callback_port: int
    auth0_callback_path: str

    # Gateway
    gateway_url: str | None = None


def get_auth_service_names() -> list[str]:
    """Get configured authentication service names."""
    auth_config = get_config()["auth"]
    services = auth_config.get("services")
    if isinstance(services, dict) and services:
        return list(services.keys())
    return ["asta"]


def get_auth_settings(service_name: str = "asta") -> AuthSettings:
    """
    Get authentication settings from configuration file.

    Args:
        service_name: Named auth service to load

    Returns:
        Authentication settings loaded from config file with env var overrides
    """
    config = get_config()["auth"]
    services = config.get("services", {})
    service_config = services.get(service_name)

    if service_config is None:
        if service_name != "asta":
            raise KeyError(f"Authentication service '{service_name}' not found")
        service_config = config

    return AuthSettings(
        service_name=service_name,
        auth0_domain=service_config.get("auth0_domain", config["auth0_domain"]),
        auth0_client_id=service_config.get(
            "auth0_client_id", config["auth0_client_id"]
        ),
        auth0_audience=service_config.get("auth0_audience", config["auth0_audience"]),
        auth0_scopes=service_config.get(
            "auth0_scopes",
            config.get("auth0_scopes", DEFAULT_AUTH0_SCOPES),
        ),
        auth0_callback_host=service_config.get(
            "auth0_callback_host",
            config.get("auth0_callback_host", "127.0.0.1"),
        ),
        auth0_callback_port=int(
            service_config.get(
                "auth0_callback_port",
                config.get("auth0_callback_port", 53147),
            )
        ),
        auth0_callback_path=service_config.get(
            "auth0_callback_path",
            config.get("auth0_callback_path", "/callback"),
        ),
        gateway_url=service_config.get("gateway_url", config.get("gateway_url")),
    )
