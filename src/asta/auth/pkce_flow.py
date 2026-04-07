"""Authorization Code + PKCE flow for native CLI login."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .device_flow import TokenResponse
from .exceptions import AuthenticationError, AuthenticationTimeout


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


@dataclass
class AuthorizationRequest:
    """Browser authorization request details."""

    authorization_url: str
    redirect_uri: str
    code_verifier: str
    state: str
    server: HTTPServer
    callback_event: threading.Event
    callback_data: dict[str, str]


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handle the Auth0 redirect callback."""

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        self.server.callback_data.update(  # type: ignore[attr-defined]
            {
                "path": parsed.path,
                "code": query.get("code", [None])[0],
                "state": query.get("state", [None])[0],
                "error": query.get("error", [None])[0],
                "error_description": query.get("error_description", [None])[0],
            }
        )
        self.server.callback_event.set()  # type: ignore[attr-defined]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Authentication complete.</h2>"
            b"<p>You can return to the terminal.</p></body></html>"
        )

    def log_message(self, format, *args):  # noqa: A003
        return


class PkceAuthFlow:
    """Authorization Code + PKCE flow for native apps."""

    def __init__(
        self,
        domain: str,
        client_id: str,
        audience: str,
        scopes: str,
        callback_host: str = "127.0.0.1",
        callback_port: int = 53147,
        callback_path: str = "/callback",
    ):
        self.domain = domain
        self.client_id = client_id
        self.audience = audience
        self.scopes = scopes
        self.callback_host = callback_host
        self.callback_port = callback_port
        self.callback_path = callback_path
        self.authorize_url = f"https://{domain}/authorize"
        self.token_url = f"https://{domain}/oauth/token"

    def start_login(self) -> AuthorizationRequest:
        """Create a browser login request and start the loopback server."""
        code_verifier = _base64url(secrets.token_bytes(64))
        code_challenge = _base64url(hashlib.sha256(code_verifier.encode()).digest())
        state = secrets.token_urlsafe(32)

        callback_event = threading.Event()
        callback_data: dict[str, str] = {}

        server = HTTPServer((self.callback_host, self.callback_port), _CallbackHandler)
        server.callback_event = callback_event  # type: ignore[attr-defined]
        server.callback_data = callback_data  # type: ignore[attr-defined]

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        redirect_uri = (
            f"http://{self.callback_host}:{server.server_port}{self.callback_path}"
        )
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.scopes,
            "audience": self.audience,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }

        return AuthorizationRequest(
            authorization_url=f"{self.authorize_url}?{urlencode(params)}",
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            state=state,
            server=server,
            callback_event=callback_event,
            callback_data=callback_data,
        )

    async def complete_login(
        self, request: AuthorizationRequest, timeout: int = 300
    ) -> TokenResponse:
        """Wait for the callback and exchange the code for tokens."""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, request.callback_event.wait, timeout)

            if not request.callback_event.is_set():
                raise AuthenticationTimeout("Authentication timeout")

            if request.callback_data.get("error"):
                error = request.callback_data["error"]
                description = request.callback_data.get("error_description") or error
                raise AuthenticationError(description)

            if request.callback_data.get("state") != request.state:
                raise AuthenticationError("Authentication state mismatch")

            if request.callback_data.get("path") != self.callback_path:
                raise AuthenticationError("Authentication callback path mismatch")

            code = request.callback_data.get("code")
            if not code:
                raise AuthenticationError("Authorization code not received")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_url,
                    data={
                        "grant_type": "authorization_code",
                        "client_id": self.client_id,
                        "code": code,
                        "code_verifier": request.code_verifier,
                        "redirect_uri": request.redirect_uri,
                    },
                )
                response.raise_for_status()
                data = response.json()

            return TokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                id_token=data.get("id_token"),
                token_type=data["token_type"],
                expires_in=data["expires_in"],
                scope=data.get("scope", ""),
            )
        except httpx.HTTPError as e:
            raise AuthenticationError(f"Authentication failed: {e}") from e
        finally:
            request.server.shutdown()
            request.server.server_close()
