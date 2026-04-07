"""Helper utilities for authentication in CLI commands."""

import asyncio
import os

from asta.auth.exceptions import AuthenticationError
from asta.auth.token_manager import TokenManager
from asta.utils.auth_config import get_auth_settings


def _token_env_var_name(service_name: str) -> str:
    if service_name == "asta":
        return "ASTA_TOKEN"
    return f"ASTA_TOKEN_{service_name.upper().replace('-', '_')}"


def get_access_token(service_name: str = "asta") -> str:
    """
    Get a valid access token, automatically refreshing if necessary.

    Returns:
        Valid access token string

    Raises:
        AuthenticationError: If not authenticated or token refresh fails.
            The error message prompts the user to run 'asta auth login'.

    Note:
        This function handles token refresh automatically. If the token
        is expired and a refresh token is available, it will be refreshed.
    """
    if token := os.environ.get(_token_env_var_name(service_name)):
        return token

    try:
        settings = get_auth_settings(service_name=service_name)

        manager = TokenManager(
            auth0_domain=settings.auth0_domain,
            client_id=settings.auth0_client_id,
            audience=settings.auth0_audience,
            scopes=settings.auth0_scopes,
            callback_host=settings.auth0_callback_host,
            callback_port=settings.auth0_callback_port,
            callback_path=settings.auth0_callback_path,
            gateway_url=settings.gateway_url,
            service_name=service_name,
        )

        return asyncio.run(manager.get_valid_access_token())

    except AuthenticationError:
        # Re-raise with original message preserved (includes refresh failure details)
        raise
    except Exception as e:
        # Convert any other errors to AuthenticationError with helpful message
        raise AuthenticationError(
            f"Authentication error: {e}\n"
            "Please run 'asta auth login' to re-authenticate."
        )
