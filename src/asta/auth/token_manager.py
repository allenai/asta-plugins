"""
High-level token management with automatic refresh.
"""

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
import webbrowser

from jose import jwt
from rich.console import Console
from rich.panel import Panel

from .device_flow import DeviceAuthFlow, TokenResponse
from .exceptions import AuthenticationError
from .pkce_flow import AuthorizationRequest, PkceAuthFlow
from .storage import TokenStorage

logger = logging.getLogger(__name__)

# Retry settings for token refresh
REFRESH_MAX_RETRIES = 3
REFRESH_RETRY_DELAY = 2  # seconds, doubles each retry


class TokenManager:
    """Manages authentication tokens with automatic refresh."""

    def __init__(
        self,
        auth0_domain: str,
        client_id: str,
        audience: str,
        scopes: str | None = None,
        callback_host: str = "127.0.0.1",
        callback_port: int = 53147,
        callback_path: str = "/callback",
        gateway_url: str | None = None,
        storage: TokenStorage | None = None,
        service_name: str = "asta",
    ):
        self.auth0_domain = auth0_domain
        self.client_id = client_id
        self.audience = audience
        self.scopes = scopes or "openid profile email offline_access access:all"
        self.flow = DeviceAuthFlow(
            auth0_domain,
            client_id,
            audience,
            self.scopes,
        )
        self.browser_flow = PkceAuthFlow(
            auth0_domain,
            client_id,
            audience,
            self.scopes,
            callback_host=callback_host,
            callback_port=callback_port,
            callback_path=callback_path,
        )
        self.storage = storage or TokenStorage()
        self.gateway_url = gateway_url
        self.service_name = service_name

    async def login(self, open_browser: bool = True) -> TokenResponse:
        """
        Perform device authorization login.

        Args:
            open_browser: Whether to automatically open browser

        Returns:
            Token response
        """
        auth_request = self.browser_flow.start_login()
        self._display_instructions(auth_request, open_browser)
        token_response = await self.browser_flow.complete_login(auth_request)
        self._save_token_response(token_response)

        return token_response

    def _save_token_response(self, token_response: TokenResponse) -> None:
        """Persist session and service token data."""
        existing_session = self.storage.load_session() or {}
        session = {
            **existing_session,
            **{
                key: value
                for key, value in {
                    "refresh_token": token_response.refresh_token
                    or existing_session.get("refresh_token"),
                    "id_token": token_response.id_token or existing_session.get("id_token"),
                }.items()
                if value
            },
        }
        if session:
            self.storage.save_session(session)

        self.storage.save_tokens(
            {
                "access_token": token_response.access_token,
                "expires_at": int(time.time()) + token_response.expires_in,
                "scope": token_response.scope,
            },
            service=self.service_name,
        )

    def _display_instructions(
        self, response: AuthorizationRequest, open_browser: bool
    ) -> None:
        """Display authentication instructions to user."""
        console = Console()

        console.print()
        console.print(
            Panel.fit(
                f"[bold cyan]Visit:[/bold cyan] {response.authorization_url}",
                title="🔐 Authentication Required",
            )
        )
        console.print()

        if open_browser:
            webbrowser.open(response.authorization_url)
            console.print("⏳ Browser opened. Waiting for authentication...")
        else:
            console.print("⏳ Waiting for authentication...")

        console.print()

    async def get_valid_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.

        Returns:
            Valid access token

        Raises:
            AuthenticationError: If not logged in or refresh fails
        """
        tokens = self.storage.load_tokens(service=self.service_name)

        if tokens:
            access_token = tokens.get("access_token")
            expires_at = tokens.get("expires_at", 0)
            if access_token and time.time() < expires_at - 300:
                return access_token

        session = self.storage.load_session() or {}
        refresh_token = session.get("refresh_token")
        if not refresh_token:
            raise AuthenticationError(
                "Not authenticated. Run 'asta auth login' to authenticate."
            )

        last_error = None
        for attempt in range(REFRESH_MAX_RETRIES):
            try:
                if attempt > 0:
                    delay = REFRESH_RETRY_DELAY * (2 ** (attempt - 1))
                    logger.info(
                        "Retrying token refresh (attempt %d/%d) after %ds",
                        attempt + 1,
                        REFRESH_MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)

                token_response = await self.flow.refresh_token(
                    refresh_token,
                    audience=self.audience,
                    scope=self.scopes,
                )
                self._save_token_response(token_response)

                if attempt > 0:
                    logger.info("Token refresh succeeded on attempt %d", attempt + 1)

                return token_response.access_token
            except AuthenticationError:
                raise
            except Exception as e:
                last_error = e
                logger.warning(
                    "Token refresh attempt %d/%d failed: %s",
                    attempt + 1,
                    REFRESH_MAX_RETRIES,
                    e,
                )

        raise AuthenticationError(
            f"Token refresh failed after {REFRESH_MAX_RETRIES} attempts: "
            f"{last_error}. "
            f"Please re-authenticate with 'asta auth login'."
        )

    def logout(self) -> None:
        """Logout by deleting stored tokens."""
        self.storage.delete_tokens()

    def get_user_info(self) -> dict | None:
        """Get user info from ID token (if available)."""
        session = self.storage.load_session()
        id_token = session.get("id_token") if session else None

        if not id_token:
            tokens = self.storage.load_tokens(service=self.service_name) or {}
            id_token = tokens.get("id_token")

        if not id_token:
            return None

        try:
            # Decode without verification (just reading claims)
            # Disable all validation checks
            return jwt.decode(
                id_token,
                key="",
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_iat": False,
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iss": False,
                    "verify_sub": False,
                    "verify_jti": False,
                    "verify_at_hash": False,
                },
            )
        except Exception:
            return None

    def verify_token_with_gateway(self) -> dict[str, any]:
        """
        Verify the access token with the gateway server.

        Returns:
            Dictionary with verification result:
            - valid (bool): Whether the token is valid on the server
            - error (str): Error message if verification failed
            - user_info (dict): User information if token is valid

        Raises:
            AuthenticationError: If gateway_url is not configured
        """
        if not self.gateway_url:
            raise AuthenticationError("Gateway URL not configured")

        tokens = self.storage.load_tokens(service=self.service_name)
        if not tokens or not tokens.get("access_token"):
            return {"valid": False, "error": "No access token found"}

        access_token = tokens["access_token"]
        verify_url = f"{self.gateway_url}/auth/verify"

        try:
            req = urllib.request.Request(
                verify_url,
                headers={"Authorization": f"Bearer {access_token}"},
                method="GET",
            )
            response = urllib.request.urlopen(req)
            data = json.loads(response.read())
            return {"valid": True, "user_info": data}

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                error_data = json.loads(error_body)
                error_msg = error_data.get("detail", str(e))
            except json.JSONDecodeError:
                error_msg = error_body or str(e)
            return {"valid": False, "error": f"HTTP {e.code}: {error_msg}"}

        except urllib.error.URLError as e:
            return {"valid": False, "error": f"Connection error: {e.reason}"}

        except Exception as e:
            return {"valid": False, "error": f"Verification failed: {str(e)}"}
