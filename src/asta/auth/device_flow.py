"""
Auth0 Device Authorization Flow implementation.

Follows RFC 8628: https://tools.ietf.org/html/rfc8628
"""

import asyncio
import time
from dataclasses import dataclass

import httpx

from .exceptions import AuthenticationError, AuthenticationTimeout


@dataclass
class DeviceCodeResponse:
    """Response from /oauth/device/code endpoint."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass
class TokenResponse:
    """Response from /oauth/token endpoint."""

    access_token: str
    refresh_token: str | None
    id_token: str | None
    token_type: str
    expires_in: int
    scope: str


class DeviceAuthFlow:
    """Implements Auth0 Device Authorization Flow."""

    def __init__(
        self,
        domain: str,
        client_id: str,
        audience: str,
        scopes: str = "openid profile email offline_access access:all",
    ):
        self.domain = domain
        self.client_id = client_id
        self.audience = audience
        self.scopes = scopes
        self.device_code_url = f"https://{domain}/oauth/device/code"
        self.token_url = f"https://{domain}/oauth/token"

    async def initiate(self) -> DeviceCodeResponse:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.device_code_url,
                data={  # Use form data instead of JSON for better compatibility
                    "client_id": self.client_id,
                    "scope": self.scopes,
                    "audience": self.audience,
                },
            )
            response.raise_for_status()
            data = response.json()

            return DeviceCodeResponse(
                device_code=data["device_code"],
                user_code=data["user_code"],
                verification_uri=data["verification_uri"],
                verification_uri_complete=data.get(
                    "verification_uri_complete",
                    f"{data['verification_uri']}?user_code={data['user_code']}",
                ),
                expires_in=data["expires_in"],
                interval=data["interval"],
            )

    async def poll_for_token(
        self, device_code: str, interval: int, timeout: int = 900
    ) -> TokenResponse:
        """
        Step 2: Poll for access token.

        Args:
            device_code: Device code from initiate()
            interval: Polling interval in seconds
            timeout: Max time to wait in seconds

        Returns:
            Token response with access_token and refresh_token

        Raises:
            AuthenticationTimeout: If user doesn't complete auth in time
            AuthenticationError: If auth fails or user denies
        """
        start_time = time.time()
        current_interval = interval

        async with httpx.AsyncClient() as client:
            while time.time() - start_time < timeout:
                await asyncio.sleep(current_interval)

                try:
                    response = await client.post(
                        self.token_url,
                        data={  # Use form data for better OAuth compatibility
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                            "device_code": device_code,
                            "client_id": self.client_id,
                        },
                    )

                    # Success!
                    if response.status_code == 200:
                        data = response.json()
                        return TokenResponse(
                            access_token=data["access_token"],
                            refresh_token=data.get("refresh_token"),
                            id_token=data.get("id_token"),
                            token_type=data["token_type"],
                            expires_in=data["expires_in"],
                            scope=data.get("scope", ""),
                        )

                    # Handle errors
                    error_data = response.json()
                    error = error_data.get("error")

                    if error == "authorization_pending":
                        # User hasn't completed auth yet
                        continue
                    elif error == "slow_down":
                        # Increase polling interval
                        current_interval += 5
                        continue
                    elif error == "expired_token":
                        raise AuthenticationTimeout("Device code expired")
                    elif error == "access_denied":
                        raise AuthenticationError("User denied authorization")
                    else:
                        raise AuthenticationError(f"Authentication failed: {error}")

                except httpx.HTTPError as e:
                    raise AuthenticationError(f"Network error: {e}")

        raise AuthenticationTimeout("Authentication timeout")

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh an expired access token.

        Args:
            refresh_token: Refresh token from previous authentication

        Returns:
            New token response
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={  # Use form data for better OAuth compatibility
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": refresh_token,
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                raise AuthenticationError(
                    f"Token refresh failed: {error_data.get('error')}"
                )

            data = response.json()
            return TokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get(
                    "refresh_token", refresh_token
                ),  # May return same
                id_token=data.get("id_token"),
                token_type=data["token_type"],
                expires_in=data["expires_in"],
                scope=data.get("scope", ""),
            )
