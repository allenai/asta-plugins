"""
Secure token storage using platform-specific secure storage.

Falls back to file-based storage with restrictive permissions.

Both keyring and file are kept in sync to prevent token loss when
refresh token rotation is enabled (rotated tokens are single-use).
"""

import json
import logging
import os
from pathlib import Path

import keyring
from platformdirs import user_config_dir

APP_NAME = "asta-cli"
TOKEN_FILE_NAME = "tokens.json"

logger = logging.getLogger(__name__)


class TokenStorage:
    """Manages secure storage of authentication tokens."""

    def __init__(self, use_keyring: bool = True):
        self.use_keyring = use_keyring
        self.config_dir = Path(user_config_dir(APP_NAME, appauthor="AI2"))
        self.token_file = self.config_dir / TOKEN_FILE_NAME

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _normalize_store(self, data: dict | None) -> dict[str, dict]:
        """Normalize legacy single-service storage into the multi-service format."""
        if not data:
            return {"session": {}, "services": {}}

        if isinstance(data.get("services"), dict) or isinstance(data.get("session"), dict):
            services = data.get("services", {})
            session = data.get("session", {})
            if not session and isinstance(services.get("asta"), dict):
                asta_tokens = services["asta"]
                session = {
                    key: asta_tokens[key]
                    for key in ("refresh_token", "id_token")
                    if asta_tokens.get(key)
                }
            return {"session": session, "services": services}

        session = {
            key: data[key]
            for key in ("refresh_token", "id_token")
            if data.get(key)
        }
        return {"session": session, "services": {"asta": data}}

    def _load_store(self) -> dict[str, dict]:
        """Load the full token store from keyring or file."""
        if self.use_keyring:
            try:
                token_json = keyring.get_password(APP_NAME, "tokens")
                if token_json:
                    return self._normalize_store(json.loads(token_json))
            except Exception as e:
                logger.debug("Keyring load failed, trying file: %s", e)

        if self.token_file.exists():
            try:
                with open(self.token_file) as f:
                    return self._normalize_store(json.load(f))
            except Exception:
                return {"session": {}, "services": {}}

        return {"session": {}, "services": {}}

    def _save_store(self, store: dict[str, dict]) -> None:
        """Persist the full token store."""
        keyring_ok = False
        if self.use_keyring:
            try:
                keyring.set_password(APP_NAME, "tokens", json.dumps(store))
                keyring_ok = True
            except Exception as e:
                logger.debug("Keyring save failed, using file storage: %s", e)

        self._save_to_file(store)

        if not keyring_ok and self.use_keyring:
            logger.debug("Tokens saved to file only (keyring unavailable)")

    def _save_to_file(self, tokens: dict) -> None:
        """Save tokens to file with restrictive permissions."""
        with open(self.token_file, "w") as f:
            json.dump(tokens, f, indent=2)
        os.chmod(self.token_file, 0o600)

    def save_tokens(self, tokens: dict[str, str], service: str = "asta") -> None:
        """
        Save tokens securely.

        Writes to both keyring and file to prevent token loss when
        refresh token rotation invalidates old tokens. If keyring
        fails, falls back to file-only storage.
        """
        store = self._load_store()
        store["services"][service] = tokens
        self._save_store(store)

    def load_tokens(self, service: str = "asta") -> dict[str, str] | None:
        """
        Load tokens from storage.

        Prefers keyring, falls back to file. Both should be in sync
        since save_tokens writes to both.
        """
        return self._load_store()["services"].get(service)

    def load_all_tokens(self) -> dict[str, dict[str, str]]:
        """Load tokens for all configured services."""
        return self._load_store()["services"]

    def save_session(self, session: dict[str, str]) -> None:
        """Save shared session state such as the MRRT refresh token."""
        store = self._load_store()
        store["session"] = session
        self._save_store(store)

    def load_session(self) -> dict[str, str] | None:
        """Load shared session state."""
        session = self._load_store()["session"]
        return session or None

    def delete_tokens(self, service: str | None = None) -> None:
        """Delete stored tokens from all backends."""
        if service is None:
            if self.use_keyring:
                try:
                    keyring.delete_password(APP_NAME, "tokens")
                except Exception:
                    pass

            if self.token_file.exists():
                self.token_file.unlink()
            return

        store = self._load_store()
        store["services"].pop(service, None)

        if store["services"] or store["session"]:
            self._save_store(store)
        else:
            self.delete_tokens()

    def get_access_token(self, service: str = "asta") -> str | None:
        """Get just the access token."""
        tokens = self.load_tokens(service=service)
        return tokens.get("access_token") if tokens else None

    def get_refresh_token(self, service: str = "asta") -> str | None:
        """Get just the refresh token."""
        tokens = self.load_tokens(service=service)
        return tokens.get("refresh_token") if tokens else None
