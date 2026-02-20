"""Tests for the Asta CLI."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli


@pytest.fixture
def runner():
    """Provide a Click CLI test runner."""
    return CliRunner()


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_version(self, runner):
        """Test --version flag."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output

    def test_help(self, runner):
        """Test --help flag."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Science literature research tools" in result.output
        assert "literature" in result.output

    def test_literature_help(self, runner):
        """Test literature subcommand help."""
        result = runner.invoke(cli, ["literature", "--help"])
        assert result.exit_code == 0
        assert "Literature research commands" in result.output
        assert "find" in result.output


class TestFindCommand:
    """Test 'asta literature find' command."""

    def test_find_help(self, runner):
        """Test find command help."""
        result = runner.invoke(cli, ["literature", "find", "--help"])
        assert result.exit_code == 0
        assert "Find papers matching QUERY" in result.output
        assert "--timeout" in result.output
        assert "-o" in result.output or "--output" in result.output

    def test_find_missing_query(self, runner):
        """Test find command without query argument."""
        result = runner.invoke(cli, ["literature", "find"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output

    def test_find_success_stdout(self, runner):
        """Test successful find with stdout output."""
        mock_result = {
            "query": "test query",
            "widget_id": "test-widget-123",
            "status": "completed",
            "paper_count": 5,
            "widget": {
                "results": [
                    {
                        "corpusId": 123,
                        "title": "Test Paper",
                        "relevanceScore": 0.9,
                        "authors": [],
                    }
                ]
            },
        }

        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.return_value = mock_result
            MockFinder.return_value = mock_instance

            result = runner.invoke(cli, ["literature", "find", "test query", "-o", "-"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data["query"] == "test query"
        assert len(output_data["results"]) == 1
        assert output_data["results"][0]["corpusId"] == 123

    def test_find_success_file_output(self, runner, tmp_path):
        """Test successful find with file output."""
        output_file = tmp_path / "results.json"
        mock_result = {
            "query": "test query",
            "widget_id": "test-widget-123",
            "status": "completed",
            "paper_count": 5,
            "file_path": str(output_file),
            "widget": {
                "results": [
                    {
                        "corpusId": 123,
                        "title": "Test Paper",
                        "relevanceScore": 0.9,
                        "authors": [],
                    },
                    {
                        "corpusId": 456,
                        "title": "Another Paper",
                        "relevanceScore": 0.8,
                        "authors": [],
                    },
                ]
            },
        }

        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.return_value = mock_result
            MockFinder.return_value = mock_instance

            result = runner.invoke(
                cli, ["literature", "find", "test query", "-o", str(output_file)]
            )

        assert result.exit_code == 0
        assert "Search completed successfully!" in result.output
        assert "Papers found: 2" in result.output
        assert str(output_file) in result.output

    def test_find_timeout_error(self, runner):
        """Test find command with timeout error."""
        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.side_effect = TimeoutError(
                "Timeout after 300 seconds"
            )
            MockFinder.return_value = mock_instance

            result = runner.invoke(cli, ["literature", "find", "test query"])

        assert result.exit_code == 2
        assert "Timeout" in result.output

    def test_find_general_error(self, runner):
        """Test find command with general error."""
        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.side_effect = Exception("API error")
            MockFinder.return_value = mock_instance

            result = runner.invoke(cli, ["literature", "find", "test query"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_find_custom_timeout(self, runner):
        """Test find command with custom timeout."""
        mock_result = {
            "query": "test query",
            "widget_id": "test-widget-123",
            "status": "completed",
            "paper_count": 3,
            "widget": {
                "results": [
                    {
                        "corpusId": 123,
                        "title": "Test Paper",
                        "relevanceScore": 0.9,
                        "authors": [],
                    }
                ]
            },
        }

        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.return_value = mock_result
            MockFinder.return_value = mock_instance

            result = runner.invoke(
                cli, ["literature", "find", "test query", "--timeout", "60"]
            )

        assert result.exit_code == 0
        mock_instance.find_papers.assert_called_once_with(
            "test query", timeout=60, save_to_file=None
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
