"""
Secure token storage using platform-specific secure storage.

Falls back to file-based storage with restrictive permissions.
"""

import json
import os
from pathlib import Path

import keyring
from platformdirs import user_config_dir

APP_NAME = "asta-cli"
TOKEN_FILE_NAME = "tokens.json"


class TokenStorage:
    """Manages secure storage of authentication tokens."""

    def __init__(self, use_keyring: bool = True):
        self.use_keyring = use_keyring
        self.config_dir = Path(user_config_dir(APP_NAME, appauthor="AI2"))
        self.token_file = self.config_dir / TOKEN_FILE_NAME

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def save_tokens(self, tokens: dict[str, str]) -> None:
        """
        Save tokens securely.

        Tries system keyring first, falls back to file with restrictive permissions.
        """
        if self.use_keyring:
            try:
                keyring.set_password(APP_NAME, "tokens", json.dumps(tokens))
                return
            except Exception:
                # Keyring failed, fall back to file
                pass

        # File-based storage
        with open(self.token_file, "w") as f:
            json.dump(tokens, f, indent=2)

        # Set restrictive permissions (owner read/write only)
        os.chmod(self.token_file, 0o600)

    def load_tokens(self) -> dict[str, str] | None:
        """Load tokens from storage."""
        if self.use_keyring:
            try:
                token_json = keyring.get_password(APP_NAME, "tokens")
                if token_json:
                    return json.loads(token_json)
            except Exception:
                pass

        # Try file-based storage
        if self.token_file.exists():
            try:
                with open(self.token_file) as f:
                    return json.load(f)
            except Exception:
                return None

        return None

    def delete_tokens(self) -> None:
        """Delete stored tokens."""
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
