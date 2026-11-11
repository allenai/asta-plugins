"""Tests for the Asta core API client."""

import json
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from asta.literature import AstaPaperFinder
from tests._v4_fixtures import v4_paper, v4_search_result, v4_sparse_paper


def mock_response(data):
    """Create a mock urllib response."""
    response = MagicMock()
    response.read.return_value = json.dumps(data).encode()
    return response


def http_error(status, body, retry_after=None):
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    error = urllib.error.HTTPError("https://test.api", status, "", headers, None)
    error.read = MagicMock(return_value=json.dumps(body).encode())
    return error


@pytest.fixture
def mock_urlopen():
    """Fixture providing mocked urlopen for AstaPaperFinder tests."""
    with patch("asta.literature.client.urllib.request.urlopen") as mock:
        yield mock


class TestAstaPaperFinder:
    """Tests for AstaPaperFinder API client on the v4 tasks API."""

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

    def test_find_papers_starts_task_and_polls_until_completed(self, mock_urlopen):
        mock_urlopen.side_effect = [
            mock_response({"taskId": "task-1", "contextId": "thrd-1"}),
            mock_response({"status": "submitted"}),
            mock_response({"status": "working"}),
            mock_response(
                {
                    "status": "completed",
                    "responseText": "Found 2 papers",
                    "artifacts": [v4_search_result([v4_paper(), v4_sparse_paper()])],
                }
            ),
        ]

        finder = AstaPaperFinder(
            base_url="https://gw/api/paper-finder", access_token="t"
        )
        with patch("asta.literature.client.time.sleep") as sleep:
            result = finder.find_papers("test query", timeout=60, operation_mode="fast")

        requests = [call.args[0] for call in mock_urlopen.call_args_list]
        assert [(r.get_method(), r.full_url) for r in requests] == [
            ("POST", "https://gw/api/paper-finder/api/4/tasks"),
            *[
                (
                    "GET",
                    "https://gw/api/paper-finder/api/4/tasks/task-1/result?preset=full",
                )
            ]
            * 3,
        ]
        assert json.loads(requests[0].data) == {
            "query": "test query",
            "operation_mode": "fast",
            "worker_profile": "standard",
            "caller": {"surface": "headless"},
        }
        assert sleep.call_count == 2
        assert result["status"] == "completed"
        assert result["paper_count"] == 2
        assert result["widget"]["response_text"] == "Found 2 papers"
        assert [p["corpusId"] for p in result["widget"]["results"]] == [
            13756489,
            52967399,
        ]
        assert result["widget"]["results"][1]["relevanceScore"] is None
        assert "file_path" not in result

    def test_find_papers_with_file_output(self, mock_urlopen, tmp_path):
        mock_urlopen.side_effect = [
            mock_response({"taskId": "task-1"}),
            mock_response(
                {"status": "completed", "artifacts": [v4_search_result([v4_paper()])]}
            ),
        ]

        finder = AstaPaperFinder(base_url="https://test.api", access_token="t")
        output_file = tmp_path / "results.json"
        result = finder.find_papers("test query", save_to_file=output_file)

        assert result["file_path"] == str(output_file)
        data = json.loads(output_file.read_text())
        assert data["paper_count"] == 1
        assert data["widget"]["results"][0]["title"] == "Attention Is All You Need"

    def test_find_papers_failed_task_raises_its_error(self, mock_urlopen):
        mock_urlopen.side_effect = [
            mock_response({"taskId": "task-1"}),
            mock_response(
                {
                    "status": "failed",
                    "error": {
                        "type": "task_failed",
                        "message": "The query was refused",
                        "code": "refused",
                    },
                }
            ),
        ]

        finder = AstaPaperFinder(base_url="https://test.api", access_token="t")
        with pytest.raises(
            Exception, match=r"Paper search failed: The query was refused \(refused\)"
        ):
            finder.find_papers("test query")

    def test_find_papers_waits_out_a_full_queue(self, mock_urlopen):
        mock_urlopen.side_effect = [
            http_error(503, {"detail": "Paper Finder is busy"}, retry_after="7"),
            mock_response({"taskId": "task-1"}),
            mock_response({"status": "completed", "artifacts": []}),
        ]

        finder = AstaPaperFinder(base_url="https://test.api", access_token="t")
        with patch("asta.literature.client.time.sleep") as sleep:
            result = finder.find_papers("test query", timeout=60)

        sleep.assert_called_once_with(7)
        assert result["paper_count"] == 0

    def test_find_papers_full_queue_past_the_deadline_raises(self, mock_urlopen):
        mock_urlopen.side_effect = [
            http_error(503, {"detail": "Paper Finder is busy"}, retry_after="30"),
        ]

        finder = AstaPaperFinder(base_url="https://test.api", access_token="t")
        with pytest.raises(Exception, match="API request failed: Paper Finder is busy"):
            finder.find_papers("test query", timeout=10)

    def test_find_papers_unknown_task_raises(self, mock_urlopen):
        mock_urlopen.side_effect = [
            mock_response({"taskId": "task-1"}),
            http_error(404, {"detail": "Task task-1 not found"}),
        ]

        finder = AstaPaperFinder(base_url="https://test.api", access_token="t")
        with pytest.raises(
            Exception, match="API request failed: Task task-1 not found"
        ):
            finder.find_papers("test query")

    def test_find_papers_times_out_naming_the_task(self, mock_urlopen):
        mock_urlopen.side_effect = [
            mock_response({"taskId": "task-1"}),
            mock_response({"status": "working"}),
            mock_response({"status": "working"}),
        ]
        clock = iter([0.0, 0.0, 9.0])

        finder = AstaPaperFinder(base_url="https://test.api", access_token="t")
        with (
            patch("asta.literature.client.time.monotonic", side_effect=clock),
            patch("asta.literature.client.time.sleep"),
            pytest.raises(
                TimeoutError,
                match="Paper search task task-1 did not finish within 10s",
            ),
        ):
            finder.find_papers("test query", timeout=10)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
