"""Tests for the Asta core API client."""

import json
from unittest.mock import MagicMock, patch

import pytest

from asta.core import AstaPaperFinder


def mock_response(data):
    """Create a mock urllib response."""
    response = MagicMock()
    response.read.return_value = json.dumps(data).encode()
    return response


@pytest.fixture
def mock_urlopen():
    """Fixture providing mocked urlopen for AstaPaperFinder tests."""
    with patch("asta.core.client.urllib.request.urlopen") as mock:
        yield mock


class TestAstaPaperFinder:
    """Tests for AstaPaperFinder API client using async headless endpoint."""

    def test_start_search(self, mock_urlopen):
        """Test starting a search returns task_id."""
        mock_urlopen.return_value = mock_response({"task_id": "task-123"})

        finder = AstaPaperFinder()
        task_id = finder.start_search("test query")

        assert task_id == "task-123"
        mock_urlopen.assert_called_once()

    def test_poll_for_results_completed(self, mock_urlopen):
        """Test polling returns completed results."""
        mock_urlopen.return_value = mock_response(
            {
                "status": "completed",
                "response_text": "Found papers",
                "papers": [{"corpus_id": 123, "title": "Test", "relevance_score": 0.9}],
                "error": None,
            }
        )

        finder = AstaPaperFinder()
        result = finder.poll_for_results("task-123", timeout=10)

        assert result["status"] == "completed"
        assert len(result["papers"]) == 1

    def test_poll_for_results_with_retry(self, mock_urlopen):
        """Test polling retries on pending status."""
        mock_urlopen.side_effect = [
            mock_response({"status": "pending"}),
            mock_response({"status": "pending"}),
            mock_response(
                {
                    "status": "completed",
                    "papers": [
                        {"corpus_id": 123, "title": "Test", "relevance_score": 0.9}
                    ],
                    "error": None,
                }
            ),
        ]

        finder = AstaPaperFinder()
        with patch("asta.core.client.time.sleep"):
            result = finder.poll_for_results("task-123", timeout=10, poll_interval=1)

        assert result["status"] == "completed"
        assert mock_urlopen.call_count == 3

    def test_poll_for_results_failed(self, mock_urlopen):
        """Test polling raises on failed status."""
        mock_urlopen.return_value = mock_response(
            {
                "status": "failed",
                "error": {"message": "Search failed", "type": "search_error"},
            }
        )

        finder = AstaPaperFinder()
        with pytest.raises(Exception, match="Paper search failed: Search failed"):
            finder.poll_for_results("task-123", timeout=10)

    def test_poll_for_results_timeout(self, mock_urlopen):
        """Test polling times out if task never completes."""
        mock_urlopen.return_value = mock_response({"status": "pending"})

        finder = AstaPaperFinder()
        with patch("asta.core.client.time.sleep"):
            with pytest.raises(TimeoutError, match="Search timed out"):
                finder.poll_for_results("task-123", timeout=5, poll_interval=1)

    def test_find_papers_success(self, mock_urlopen):
        """Test successful end-to-end paper search."""
        mock_urlopen.side_effect = [
            # start_search response
            mock_response({"task_id": "task-123"}),
            # poll_for_results response
            mock_response(
                {
                    "status": "completed",
                    "response_text": "Found 2 papers",
                    "papers": [
                        {
                            "corpus_id": 12345,
                            "title": "Test Paper",
                            "abstract": "Test abstract",
                            "authors": ["Alice", "Bob"],
                            "venue": "NeurIPS",
                            "year": 2024,
                            "relevance_score": 0.95,
                        },
                        {
                            "corpus_id": 67890,
                            "title": "Another Paper",
                            "authors": ["Charlie"],
                            "relevance_score": 0.85,
                        },
                    ],
                    "error": None,
                }
            ),
        ]

        finder = AstaPaperFinder()
        result = finder.find_papers("test query", timeout=10)

        assert result["status"] == "completed"
        assert result["paper_count"] == 2
        assert result["query"] == "test query"
        assert result["task_id"] == "task-123"
        assert len(result["widget"]["results"]) == 2
        assert "file_path" not in result

    def test_find_papers_with_file_output(self, mock_urlopen, tmp_path):
        """Test find_papers with file output."""
        mock_urlopen.side_effect = [
            mock_response({"task_id": "task-456"}),
            mock_response(
                {
                    "status": "completed",
                    "response_text": "Found 1 paper",
                    "papers": [
                        {
                            "corpus_id": 12345,
                            "title": "Test Paper",
                            "authors": ["Alice"],
                            "relevance_score": 0.95,
                        }
                    ],
                    "error": None,
                }
            ),
        ]

        finder = AstaPaperFinder()
        output_file = tmp_path / "results.json"
        result = finder.find_papers("test query", timeout=10, save_to_file=output_file)

        assert result["paper_count"] == 1
        assert result["task_id"] == "task-456"
        assert result["file_path"] == str(output_file)

        assert output_file.exists()
        with open(output_file) as f:
            data = json.load(f)
        assert data["paper_count"] == 1
        assert data["status"] == "completed"

    def test_find_papers_with_operation_modes(self, mock_urlopen):
        """Test find_papers with different operation modes."""
        mock_urlopen.side_effect = [
            mock_response({"task_id": "task-789"}),
            mock_response(
                {
                    "status": "completed",
                    "papers": [
                        {"corpus_id": 123, "title": "Test", "relevance_score": 0.9}
                    ],
                    "error": None,
                }
            ),
        ]

        finder = AstaPaperFinder()
        result = finder.find_papers("test query", operation_mode="fast")

        assert result["status"] == "completed"
        assert result["task_id"] == "task-789"

    def test_find_papers_search_failed(self, mock_urlopen):
        """Test find_papers when search fails."""
        mock_urlopen.side_effect = [
            mock_response({"task_id": "task-999"}),
            mock_response(
                {
                    "status": "failed",
                    "error": {"message": "Search failed", "type": "search_error"},
                }
            ),
        ]

        finder = AstaPaperFinder()
        with pytest.raises(Exception, match="Paper search failed"):
            finder.find_papers("test query", timeout=10)

    def test_start_search_http_error(self, mock_urlopen):
        """Test start_search with HTTP error."""
        import urllib.error

        error = urllib.error.HTTPError("https://test.com", 400, "Bad Request", {}, None)
        error.read = MagicMock(
            return_value=json.dumps({"detail": "Invalid query"}).encode()
        )
        mock_urlopen.side_effect = error

        finder = AstaPaperFinder()
        with pytest.raises(Exception, match="API request failed: Invalid query"):
            finder.start_search("test query")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
