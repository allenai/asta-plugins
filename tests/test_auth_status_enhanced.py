"""Tests for enhanced auth status command."""

import time
from unittest.mock import patch

from click.testing import CliRunner

from asta.auth.storage import TokenStorage
from asta.cli import cli


class TestEnhancedAuthStatus:
    """Tests for enhanced auth status functionality."""

    def test_status_with_valid_token_and_refresh(self):
        """Test status with valid token and refresh token available."""
        runner = CliRunner()

        # Mock tokens with valid access token and refresh token
        mock_tokens = {
            "access_token": "valid-token",
            "refresh_token": "refresh-token",
            "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAdGVzdC5jb20iLCJuYW1lIjoiVGVzdCBVc2VyIn0.test",
            "expires_at": int(time.time()) + 3600,  # Expires in 1 hour
        }

        with patch.object(TokenStorage, "load_tokens", return_value=mock_tokens):
            result = runner.invoke(cli, ["auth", "status"])
            assert result.exit_code == 0
            assert "Valid" in result.output
            assert "Available" in result.output  # Refresh token
            assert "Auto-Refresh" in result.output
            assert "Enabled" in result.output

    def test_status_with_expiring_token(self):
        """Test status with token expiring soon (within 5 min)."""
        runner = CliRunner()

        # Mock tokens with token expiring in 4 minutes
        mock_tokens = {
            "access_token": "expiring-token",
            "refresh_token": "refresh-token",
            "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAdGVzdC5jb20iLCJuYW1lIjoiVGVzdCBVc2VyIn0.test",
            "expires_at": int(time.time()) + 240,  # Expires in 4 minutes
        }

        with patch.object(TokenStorage, "load_tokens", return_value=mock_tokens):
            result = runner.invoke(cli, ["auth", "status"])
            assert result.exit_code == 0
            assert "Expiring soon" in result.output
            assert "will auto-refresh" in result.output

    def test_status_with_expired_token_with_refresh(self):
        """Test status with expired token but refresh token available."""
        runner = CliRunner()

        # Mock tokens with expired access token but valid refresh token
        mock_tokens = {
            "access_token": "expired-token",
            "refresh_token": "refresh-token",
            "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAdGVzdC5jb20iLCJuYW1lIjoiVGVzdCBVc2VyIn0.test",
            "expires_at": int(time.time()) - 3600,  # Expired 1 hour ago
        }

        with patch.object(TokenStorage, "load_tokens", return_value=mock_tokens):
            result = runner.invoke(cli, ["auth", "status"])
            assert result.exit_code == 0
            assert "Expired" in result.output
            assert "will auto-refresh" in result.output
            assert "Available" in result.output  # Refresh token

    def test_status_with_expired_token_no_refresh(self):
        """Test status with expired token and no refresh token."""
        runner = CliRunner()

        # Mock tokens with expired access token and no refresh token
        mock_tokens = {
            "access_token": "expired-token",
            "refresh_token": None,
            "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAdGVzdC5jb20iLCJuYW1lIjoiVGVzdCBVc2VyIn0.test",
            "expires_at": int(time.time()) - 3600,  # Expired 1 hour ago
        }

        with patch.object(TokenStorage, "load_tokens", return_value=mock_tokens):
            result = runner.invoke(cli, ["auth", "status"])
            assert result.exit_code == 0
            assert "Expired" in result.output
            assert "re-login required" in result.output
            assert "Not available" in result.output  # No refresh token
            assert "Your access token has expired" in result.output
