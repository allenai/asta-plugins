"""Tests for auth helper utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAuthHelper:
    """Test auth helper functions."""

    def test_get_access_token_with_valid_token(self):
        """Test getting access token when a valid one exists."""
        from asta.utils.auth_helper import get_access_token

        with patch("asta.utils.auth_helper.get_auth_settings") as mock_settings:
            with patch("asta.utils.auth_helper.TokenManager") as MockManager:
                # Mock settings
                mock_settings.return_value = MagicMock(
                    auth0_domain="test.auth0.com",
                    auth0_client_id="test-client",
                    auth0_audience="test-audience",
                    gateway_url="https://test.gateway",
                )

                # Mock token manager
                mock_manager = MagicMock()
                mock_manager.get_valid_access_token = AsyncMock(
                    return_value="test-token-123"
                )
                MockManager.return_value = mock_manager

                token = get_access_token()
                assert token == "test-token-123"

    def test_get_access_token_without_token(self):
        """Test getting access token when none exists."""
        from asta.auth.exceptions import AuthenticationError
        from asta.utils.auth_helper import get_access_token

        with patch("asta.utils.auth_helper.get_auth_settings") as mock_settings:
            with patch("asta.utils.auth_helper.TokenManager") as MockManager:
                # Mock settings
                mock_settings.return_value = MagicMock(
                    auth0_domain="test.auth0.com",
                    auth0_client_id="test-client",
                    auth0_audience="test-audience",
                    gateway_url="https://test.gateway",
                )

                # Mock token manager to raise AuthenticationError
                mock_manager = MagicMock()
                mock_manager.get_valid_access_token = AsyncMock(
                    side_effect=AuthenticationError("Not authenticated")
                )
                MockManager.return_value = mock_manager

                with pytest.raises(AuthenticationError):
                    get_access_token()

    def test_get_access_token_refresh_failure(self):
        """Test that token refresh failures are re-raised with original message."""
        from asta.auth.exceptions import AuthenticationError
        from asta.utils.auth_helper import get_access_token

        with patch("asta.utils.auth_helper.get_auth_settings") as mock_settings:
            with patch("asta.utils.auth_helper.TokenManager") as MockManager:
                # Mock settings
                mock_settings.return_value = MagicMock(
                    auth0_domain="test.auth0.com",
                    auth0_client_id="test-client",
                    auth0_audience="test-audience",
                    gateway_url="https://test.gateway",
                )

                # Mock token manager to raise AuthenticationError on refresh
                mock_manager = MagicMock()
                mock_manager.get_valid_access_token = AsyncMock(
                    side_effect=AuthenticationError("Token refresh failed")
                )
                MockManager.return_value = mock_manager

                with pytest.raises(AuthenticationError):
                    get_access_token()

    def test_get_access_token_other_error(self):
        """Test that other errors are converted to AuthenticationError."""
        from asta.auth.exceptions import AuthenticationError
        from asta.utils.auth_helper import get_access_token

        with patch("asta.utils.auth_helper.get_auth_settings") as mock_settings:
            # Mock settings to raise an exception
            mock_settings.side_effect = Exception("Config error")

            with pytest.raises(
                AuthenticationError, match="Please run 'asta auth login'"
            ):
                get_access_token()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
