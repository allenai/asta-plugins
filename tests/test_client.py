"""Tests for the Asta core API client."""

import json
from unittest.mock import MagicMock, patch

import pytest

from asta.literature import AstaPaperFinder


def mock_response(data):
    """Create a mock urllib response."""
    response = MagicMock()
    response.read.return_value = json.dumps(data).encode()
    return response


@pytest.fixture
def mock_urlopen():
    """Fixture providing mocked urlopen for AstaPaperFinder tests."""
    with patch("asta.literature.client.urllib.request.urlopen") as mock:
        yield mock


class TestAstaPaperFinder:
    """Tests for AstaPaperFinder API client using headless endpoint."""

    def test_init_with_explicit_params(self):
        """Test that client initializes with explicit parameters."""
        custom_url = "https://custom.api.example.com"
        token = "test-token-123"
        finder = AstaPaperFinder(base_url=custom_url, access_token=token)
        assert finder.base_url == custom_url
        assert finder.access_token == token
        assert "Authorization" in finder.headers
        assert finder.headers["Authorization"] == f"Bearer {token}"

    def test_init_from_config(self):
        """Test that client loads from config when available."""
        with patch("asta.literature.client.get_api_config") as mock_get_api:
            with patch("asta.literature.client.get_access_token") as mock_get_token:
                mock_get_api.return_value = {"base_url": "https://config.url"}
                mock_get_token.return_value = "config-token"

                finder = AstaPaperFinder()
                assert finder.base_url == "https://config.url"
                assert finder.access_token == "config-token"

    def test_init_fails_without_base_url(self):
        """Test that client fails without base_url."""
        with patch("asta.literature.client.get_api_config") as mock_get_api:
            with patch("asta.literature.client.get_access_token") as mock_get_token:
                mock_get_api.side_effect = KeyError("Not found")
                mock_get_token.return_value = "test-token"

                with pytest.raises(ValueError, match="base_url is required"):
                    AstaPaperFinder()

    def test_init_fails_without_access_token(self):
        """Test that client fails without access_token."""
        from asta.auth.exceptions import AuthenticationError

        with patch("asta.literature.client.get_api_config") as mock_get_api:
            with patch("asta.literature.client.get_access_token") as mock_get_token:
                mock_get_api.return_value = {"base_url": "https://test.url"}
                mock_get_token.side_effect = AuthenticationError(
                    "Not authenticated. Please run 'asta auth login' to authenticate."
                )

                with pytest.raises(
                    AuthenticationError, match="Please run 'asta auth login'"
                ):
                    AstaPaperFinder()

    def test_find_papers_success(self, mock_urlopen):
        """Test successful paper search."""
        mock_urlopen.return_value = mock_response(
            {
                "response_text": "Found 2 papers",
                "papers": [
                    {
                        "corpusId": 12345,
                        "title": "Test Paper",
                        "abstract": "Test abstract",
                        "authors": [{"name": "Alice", "authorId": "1"}],
                        "venue": "NeurIPS",
                        "year": 2024,
                        "relevanceScore": 0.95,
                    },
                    {
                        "corpusId": 67890,
                        "title": "Another Paper",
                        "abstract": "Another abstract",
                        "authors": [{"name": "Bob", "authorId": "2"}],
                        "venue": "ICML",
                        "year": 2023,
                        "relevanceScore": 0.85,
                    },
                ],
                "error": None,
            }
        )

        finder = AstaPaperFinder(base_url="https://test.api", access_token="test-token")
        result = finder.find_papers("test query", timeout=10)

        assert result["status"] == "completed"
        assert result["paper_count"] == 2
        assert result["query"] == "test query"
        assert len(result["widget"]["results"]) == 2
        assert result["widget"]["results"][0]["corpusId"] == 12345
        assert "file_path" not in result

    def test_find_papers_with_file_output(self, mock_urlopen, tmp_path):
        """Test find_papers with file output."""
        mock_urlopen.return_value = mock_response(
            {
                "response_text": "Found 1 paper",
                "papers": [
                    {
                        "corpusId": 12345,
                        "title": "Test Paper",
                        "authors": [{"name": "Alice", "authorId": "1"}],
                        "venue": "NeurIPS",
                        "year": 2024,
                        "relevanceScore": 0.95,
                    }
                ],
                "error": None,
            }
        )

        finder = AstaPaperFinder(base_url="https://test.api", access_token="test-token")
        output_file = tmp_path / "results.json"
        result = finder.find_papers("test query", timeout=10, save_to_file=output_file)

        assert result["paper_count"] == 1
        assert result["file_path"] == str(output_file)

        assert output_file.exists()
        with open(output_file) as f:
            data = json.load(f)
        assert data["paper_count"] == 1
        assert data["status"] == "completed"

    def test_find_papers_with_error(self, mock_urlopen):
        """Test find_papers when API returns an error."""
        mock_urlopen.return_value = mock_response(
            {
                "response_text": "",
                "papers": [],
                "error": {"message": "Search failed", "type": "search_error"},
            }
        )

        finder = AstaPaperFinder(base_url="https://test.api", access_token="test-token")
        with pytest.raises(Exception, match="Paper search failed"):
            finder.find_papers("test query", timeout=10)

    def test_find_papers_with_operation_modes(self, mock_urlopen):
        """Test find_papers with different operation modes."""
        mock_urlopen.return_value = mock_response(
            {
                "response_text": "Found papers",
                "papers": [{"corpusId": 123, "title": "Test", "relevanceScore": 0.9}],
                "error": None,
            }
        )

        finder = AstaPaperFinder(base_url="https://test.api", access_token="test-token")

        # Test each operation mode
        for mode in ["infer", "fast", "diligent"]:
            result = finder.find_papers("test query", operation_mode=mode)
            assert result["status"] == "completed"

    def test_find_papers_http_error(self, mock_urlopen):
        """Test find_papers with HTTP error."""
        import urllib.error

        error = urllib.error.HTTPError("https://test.com", 400, "Bad Request", {}, None)
        error.read = MagicMock(
            return_value=json.dumps({"detail": "Invalid query"}).encode()
        )
        mock_urlopen.side_effect = error

        finder = AstaPaperFinder(base_url="https://test.api", access_token="test-token")
        with pytest.raises(Exception, match="API request failed: Invalid query"):
            finder.find_papers("test query")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
