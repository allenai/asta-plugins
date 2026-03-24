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

    def _save_to_file(self, tokens: dict[str, str]) -> None:
        """Save tokens to file with restrictive permissions."""
        with open(self.token_file, "w") as f:
            json.dump(tokens, f, indent=2)
        os.chmod(self.token_file, 0o600)

    def save_tokens(self, tokens: dict[str, str]) -> None:
        """
        Save tokens securely.

        Writes to both keyring and file to prevent token loss when
        refresh token rotation invalidates old tokens. If keyring
        fails, falls back to file-only storage.
        """
        keyring_ok = False
        if self.use_keyring:
            try:
                keyring.set_password(APP_NAME, "tokens", json.dumps(tokens))
                keyring_ok = True
            except Exception as e:
                logger.debug("Keyring save failed, using file storage: %s", e)

        # Always save to file as well — ensures consistency if keyring
        # becomes unavailable on a future read after token rotation.
        self._save_to_file(tokens)

        if not keyring_ok and self.use_keyring:
            logger.debug("Tokens saved to file only (keyring unavailable)")

    def load_tokens(self) -> dict[str, str] | None:
        """
        Load tokens from storage.

        Prefers keyring, falls back to file. Both should be in sync
        since save_tokens writes to both.
        """
        if self.use_keyring:
            try:
                token_json = keyring.get_password(APP_NAME, "tokens")
                if token_json:
                    return json.loads(token_json)
            except Exception as e:
                logger.debug("Keyring load failed, trying file: %s", e)

        # Try file-based storage
        if self.token_file.exists():
            try:
                with open(self.token_file) as f:
                    return json.load(f)
            except Exception:
                return None

        return None

    def delete_tokens(self) -> None:
        """Delete stored tokens from all backends."""
        if self.use_keyring:
            try:
                keyring.delete_password(APP_NAME, "tokens")
            except Exception:
                pass

        if self.token_file.exists():
            self.token_file.unlink()

    def get_access_token(self) -> str | None:
        """Get just the access token."""
        tokens = self.load_tokens()
        return tokens.get("access_token") if tokens else None

    def get_refresh_token(self) -> str | None:
        """Get just the refresh token."""
        tokens = self.load_tokens()
        return tokens.get("refresh_token") if tokens else None
