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
    """Tests for AstaPaperFinder API client."""

    def test_create_thread(self, mock_urlopen):
        """Test thread creation."""
        mock_urlopen.return_value = mock_response(
            {"thread": {"key": "test-thread-123"}}
        )

        finder = AstaPaperFinder()
        thread_id = finder.create_thread()

        assert thread_id == "test-thread-123"
        mock_urlopen.assert_called_once()

    def test_send_message(self, mock_urlopen):
        """Test sending a message to thread."""
        mock_urlopen.return_value = mock_response({"message_id": "msg-123"})

        finder = AstaPaperFinder()
        result = finder.send_message("test query", "thread-123")

        assert result == {"message_id": "msg-123"}
        mock_urlopen.assert_called_once()

    def test_get_widget_id_success(self, mock_urlopen):
        """Test getting widget ID from thread events."""
        mock_urlopen.return_value = mock_response(
            {"last_event": {"data": {"id": "widget-456"}}}
        )

        finder = AstaPaperFinder()
        widget_id = finder.get_widget_id("thread-123", max_retries=1)

        assert widget_id == "widget-456"

    def test_get_widget_id_retry_then_success(self, mock_urlopen):
        """Test widget ID retrieval with retry."""
        mock_urlopen.side_effect = [
            mock_response({"last_event": {}}),
            mock_response({"last_event": {"data": {"id": "widget-456"}}}),
        ]

        finder = AstaPaperFinder()
        with patch("asta.core.client.time.sleep"):
            widget_id = finder.get_widget_id("thread-123", max_retries=3)

        assert widget_id == "widget-456"
        assert mock_urlopen.call_count == 2

    def test_get_widget_id_timeout(self, mock_urlopen):
        """Test widget ID retrieval timeout."""
        mock_urlopen.return_value = mock_response({"last_event": {}})

        finder = AstaPaperFinder()
        with patch("asta.core.client.time.sleep"):
            widget_id = finder.get_widget_id("thread-123", max_retries=2)

        assert widget_id is None

    def test_poll_for_results_completed(self, mock_urlopen):
        """Test polling returns completed results."""
        mock_urlopen.return_value = mock_response(
            {
                "roundStatus": {"kind": "completed"},
                "results": [{"corpusId": 1, "title": "Test Paper"}],
            }
        )

        finder = AstaPaperFinder()
        result = finder.poll_for_results("widget-123", timeout=10)

        assert result["roundStatus"]["kind"] == "completed"
        assert len(result["results"]) == 1

    def test_poll_for_results_list_response(self, mock_urlopen):
        """Test polling handles list response (papers directly)."""
        mock_urlopen.return_value = mock_response([{"corpusId": 1}, {"corpusId": 2}])

        finder = AstaPaperFinder()
        result = finder.poll_for_results("widget-123", timeout=10)

        assert result["roundStatus"]["kind"] == "completed"
        assert len(result["results"]) == 2

    def test_poll_for_results_failed(self, mock_urlopen):
        """Test polling raises on failed status."""
        mock_urlopen.return_value = mock_response(
            {
                "roundStatus": {"kind": "failed", "error": "Search failed"},
            }
        )

        finder = AstaPaperFinder()
        with pytest.raises(Exception, match="Paper finder failed"):
            finder.poll_for_results("widget-123", timeout=10)

    def test_find_papers_full_flow(self, mock_urlopen, tmp_path):
        """Test complete find_papers workflow without file saving."""
        mock_urlopen.side_effect = [
            # create_thread
            mock_response({"thread": {"key": "thread-123"}}),
            # send_message
            mock_response({}),
            # get_widget_id
            mock_response({"last_event": {"data": {"id": "widget-456"}}}),
            # poll_for_results
            mock_response(
                {
                    "roundStatus": {"kind": "completed"},
                    "results": [
                        {
                            "corpusId": 12345,
                            "title": "Test Paper",
                            "authors": [{"name": "Alice"}],
                            "venue": "NeurIPS",
                            "year": 2024,
                        }
                    ],
                }
            ),
        ]

        finder = AstaPaperFinder()
        result = finder.find_papers("test query", timeout=10)

        assert result["widget_id"] == "widget-456"
        assert result["paper_count"] == 1
        assert "file_path" not in result

    def test_find_papers_with_file_output(self, mock_urlopen, tmp_path):
        """Test find_papers with file output."""
        mock_urlopen.side_effect = [
            # create_thread
            mock_response({"thread": {"key": "thread-123"}}),
            # send_message
            mock_response({}),
            # get_widget_id
            mock_response({"last_event": {"data": {"id": "widget-456"}}}),
            # poll_for_results
            mock_response(
                {
                    "roundStatus": {"kind": "completed"},
                    "results": [
                        {
                            "corpusId": 12345,
                            "title": "Test Paper",
                            "authors": [{"name": "Alice"}],
                            "venue": "NeurIPS",
                            "year": 2024,
                        }
                    ],
                }
            ),
        ]

        finder = AstaPaperFinder()
        output_file = tmp_path / "results.json"
        result = finder.find_papers("test query", timeout=10, save_to_file=output_file)

        assert result["widget_id"] == "widget-456"
        assert result["paper_count"] == 1
        assert result["file_path"] == str(output_file)

        assert output_file.exists()
        import json

        with open(output_file) as f:
            data = json.load(f)
        assert data["widget_id"] == "widget-456"
        assert data["paper_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
