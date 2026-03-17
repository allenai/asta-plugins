"""Tests for authentication module."""

import json
import time
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from asta.auth.storage import TokenStorage
from asta.auth.token_manager import TokenManager
from asta.cli import cli


class TestTokenStorage:
    """Tests for TokenStorage."""

    def test_save_and_load_tokens(self, tmp_path):
        """Test saving and loading tokens from file."""
        storage = TokenStorage(use_keyring=False)
        storage.token_file = tmp_path / "tokens.json"

        tokens = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "expires_at": 1234567890,
        }

        storage.save_tokens(tokens)
        loaded = storage.load_tokens()

        assert loaded == tokens
        assert storage.token_file.exists()

    def test_delete_tokens(self, tmp_path):
        """Test deleting tokens."""
        storage = TokenStorage(use_keyring=False)
        storage.token_file = tmp_path / "tokens.json"

        tokens = {"access_token": "test"}
        storage.save_tokens(tokens)
        assert storage.token_file.exists()

        storage.delete_tokens()
        assert not storage.token_file.exists()

    def test_get_access_token(self, tmp_path):
        """Test getting access token."""
        storage = TokenStorage(use_keyring=False)
        storage.token_file = tmp_path / "tokens.json"

        tokens = {"access_token": "test-token"}
        storage.save_tokens(tokens)

        assert storage.get_access_token() == "test-token"

    def test_load_tokens_when_none_exist(self, tmp_path):
        """Test loading tokens when none exist."""
        storage = TokenStorage(use_keyring=False)
        storage.token_file = tmp_path / "nonexistent.json"

        assert storage.load_tokens() is None


class TestAuthCommands:
    """Tests for auth CLI commands."""

    def test_auth_status_not_authenticated(self):
        """Test auth status when not authenticated."""
        runner = CliRunner()

        # Mock TokenStorage.load_tokens to return None (no tokens)
        with patch.object(TokenStorage, "load_tokens", return_value=None):
            result = runner.invoke(cli, ["auth", "status"])
            assert result.exit_code == 0
            assert "Not authenticated" in result.output

    def test_auth_status_with_server_verification(self):
        """Test auth status displays server verification result."""
        runner = CliRunner()

        # Mock tokens
        mock_tokens = {
            "access_token": "test-token",
            "refresh_token": "test-refresh",
            "id_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJuYW1lIjoiVGVzdCBVc2VyIn0.test",
            "expires_at": int(time.time()) + 3600,
        }

        # Mock verification success
        mock_verification = {
            "valid": True,
            "user_info": {"email": "test@example.com"},
        }

        with (
            patch.object(TokenStorage, "load_tokens", return_value=mock_tokens),
            patch.object(
                TokenManager,
                "verify_token_with_gateway",
                return_value=mock_verification,
            ),
        ):
            result = runner.invoke(cli, ["auth", "status"])
            assert result.exit_code == 0
            assert "Server Verification" in result.output
            assert "Valid" in result.output

    def test_auth_status_with_server_verification_failure(self):
        """Test auth status when server verification fails."""
        runner = CliRunner()

        # Mock tokens
        mock_tokens = {
            "access_token": "test-token",
            "refresh_token": "test-refresh",
            "id_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJuYW1lIjoiVGVzdCBVc2VyIn0.test",
            "expires_at": int(time.time()) + 3600,
        }

        # Mock verification failure
        mock_verification = {"valid": False, "error": "Token expired on server"}

        with (
            patch.object(TokenStorage, "load_tokens", return_value=mock_tokens),
            patch.object(
                TokenManager,
                "verify_token_with_gateway",
                return_value=mock_verification,
            ),
        ):
            result = runner.invoke(cli, ["auth", "status"])
            assert result.exit_code == 0
            assert "Server Verification" in result.output
            assert "Invalid" in result.output
            assert "Token verification failed" in result.output

    def test_auth_logout(self):
        """Test auth logout command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "logout"])
        assert result.exit_code == 0
        assert "Logged out successfully" in result.output

    def test_auth_print_token_no_token(self):
        """Test print-token when no token exists."""
        runner = CliRunner()

        # Mock TokenStorage.load_tokens to return None
        with patch.object(TokenStorage, "load_tokens", return_value=None):
            result = runner.invoke(cli, ["auth", "print-token"])
            assert result.exit_code == 1
            assert "No token found" in result.output

    def test_auth_print_token_raw(self):
        """Test print-token with --raw flag."""
        runner = CliRunner()

        # Mock token
        test_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwiZW1haWwiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiaWF0IjoxNTE2MjM5MDIyfQ.signature"
        mock_tokens = {"access_token": test_token}

        with patch.object(TokenStorage, "load_tokens", return_value=mock_tokens):
            result = runner.invoke(cli, ["auth", "print-token", "--raw"])
            assert result.exit_code == 0
            assert test_token in result.output

    def test_auth_print_token_decoded(self):
        """Test print-token without --raw flag (decoded output)."""
        runner = CliRunner()

        # Create a valid JWT token
        # Header: {"alg":"HS256","typ":"JWT"}
        # Payload: {"sub":"1234567890","email":"test@example.com","scope":"openid profile email access:semantic-scholar"}
        test_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwiZW1haWwiOiJ0ZXN0QGV4YW1wbGUuY29tIiwic2NvcGUiOiJvcGVuaWQgcHJvZmlsZSBlbWFpbCBhY2Nlc3M6c2VtYW50aWMtc2Nob2xhciJ9.signature"
        mock_tokens = {"access_token": test_token}

        with patch.object(TokenStorage, "load_tokens", return_value=mock_tokens):
            result = runner.invoke(cli, ["auth", "print-token"])
            assert result.exit_code == 0
            assert "JWT Header:" in result.output
            assert "JWT Payload:" in result.output
            assert "test@example.com" in result.output
            assert "access:semantic-scholar" in result.output


class TestTokenVerification:
    """Tests for server-side token verification."""

    def test_verify_token_with_gateway_success(self, tmp_path):
        """Test successful token verification with gateway."""
        storage = TokenStorage(use_keyring=False)
        storage.token_file = tmp_path / "tokens.json"
        storage.save_tokens(
            {
                "access_token": "valid-token",
                "expires_at": int(time.time()) + 3600,
            }
        )

        token_manager = TokenManager(
            auth0_domain="test.auth0.com",
            client_id="test-client",
            audience="test-audience",
            gateway_url="http://localhost:8080",
            storage=storage,
        )

        # Mock urllib.request.urlopen to return successful response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"sub": "user123", "email": "test@example.com"}
        ).encode()

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = token_manager.verify_token_with_gateway()
            assert result["valid"] is True
            assert "user_info" in result
            assert result["user_info"]["email"] == "test@example.com"

    def test_verify_token_with_gateway_invalid(self, tmp_path):
        """Test token verification with invalid token."""
        storage = TokenStorage(use_keyring=False)
        storage.token_file = tmp_path / "tokens.json"
        storage.save_tokens(
            {
                "access_token": "invalid-token",
                "expires_at": int(time.time()) + 3600,
            }
        )

        token_manager = TokenManager(
            auth0_domain="test.auth0.com",
            client_id="test-client",
            audience="test-audience",
            gateway_url="http://localhost:8080",
            storage=storage,
        )

        # Mock urllib.request.urlopen to raise HTTPError
        import urllib.error

        mock_error = urllib.error.HTTPError(
            url="http://localhost:8080/auth/verify",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )
        mock_error.read = lambda: b'{"detail": "Invalid token"}'

        with patch("urllib.request.urlopen", side_effect=mock_error):
            result = token_manager.verify_token_with_gateway()
            assert result["valid"] is False
            assert "error" in result
            assert "401" in result["error"]

    def test_verify_token_no_token(self, tmp_path):
        """Test verification when no token exists."""
        storage = TokenStorage(use_keyring=False)
        storage.token_file = tmp_path / "tokens.json"

        token_manager = TokenManager(
            auth0_domain="test.auth0.com",
            client_id="test-client",
            audience="test-audience",
            gateway_url="http://localhost:8080",
            storage=storage,
        )

        result = token_manager.verify_token_with_gateway()
        assert result["valid"] is False
        assert "No access token found" in result["error"]

    def test_verify_token_no_gateway_url(self, tmp_path):
        """Test verification when gateway URL is not configured."""
        storage = TokenStorage(use_keyring=False)
        storage.token_file = tmp_path / "tokens.json"
        storage.save_tokens({"access_token": "test-token"})

        token_manager = TokenManager(
            auth0_domain="test.auth0.com",
            client_id="test-client",
            audience="test-audience",
            gateway_url=None,
            storage=storage,
        )

        try:
            token_manager.verify_token_with_gateway()
            assert False, "Should have raised AuthenticationError"
        except Exception as e:
            assert "Gateway URL not configured" in str(e)
