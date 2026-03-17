"""Helper utilities for authentication in CLI commands."""

import asyncio

from asta.auth.exceptions import AuthenticationError
from asta.auth.token_manager import TokenManager
from asta.utils.auth_config import get_auth_settings


def get_access_token() -> str:
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
    try:
        # Get auth settings from config
        settings = get_auth_settings()

        # Create token manager
        manager = TokenManager(
            auth0_domain=settings.auth0_domain,
            client_id=settings.auth0_client_id,
            audience=settings.auth0_audience,
            gateway_url=settings.gateway_url,
        )

        # Get valid access token (handles refresh automatically)
        # Run async function in sync context
        return asyncio.run(manager.get_valid_access_token())

    except AuthenticationError:
        # Re-raise with user-friendly message
        raise AuthenticationError(
            "Not authenticated. Please run 'asta auth login' to authenticate."
        )
    except Exception as e:
        # Convert any other errors to AuthenticationError with helpful message
        raise AuthenticationError(
            f"Authentication error: {e}\n"
            "Please run 'asta auth login' to re-authenticate."
        )
