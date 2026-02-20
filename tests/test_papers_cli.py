"""Tests for the papers CLI commands."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli


@pytest.fixture
def runner():
    """Provide a Click CLI test runner."""
    return CliRunner()


class TestPapersBasics:
    """Test basic papers CLI functionality."""

    def test_papers_help(self, runner):
        """Test papers subcommand help."""
        result = runner.invoke(cli, ["papers", "--help"])
        assert result.exit_code == 0
        assert "Semantic Scholar paper lookup" in result.output
        assert "get" in result.output
        assert "search" in result.output
        assert "citations" in result.output
        assert "author" in result.output


class TestPapersGet:
    """Test 'asta papers get' command."""

    def test_get_help(self, runner):
        """Test papers get command help."""
        result = runner.invoke(cli, ["papers", "get", "--help"])
        assert result.exit_code == 0
        assert "Get details for a paper by ID" in result.output
        assert "ARXIV" in result.output
        assert "DOI" in result.output

    def test_get_missing_id(self, runner):
        """Test papers get without paper ID."""
        result = runner.invoke(cli, ["papers", "get"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output

    def test_get_json_format(self, runner):
        """Test papers get with JSON output."""
        mock_paper = {
            "paperId": "abc123",
            "title": "Test Paper",
            "year": 2024,
            "authors": [{"name": "John Doe"}],
        }

        with patch("asta.papers.get.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_paper.return_value = mock_paper
            MockClient.return_value = mock_instance

            result = runner.invoke(cli, ["papers", "get", "ARXIV:2005.14165"])

        assert result.exit_code == 0
        assert "Test Paper" in result.output
        assert "2024" in result.output

    def test_get_text_format(self, runner):
        """Test papers get with text output."""
        mock_paper = {
            "paperId": "abc123",
            "title": "Test Paper",
            "year": 2024,
            "authors": [{"name": "John Doe"}],
            "venue": "NeurIPS",
            "citationCount": 42,
        }

        with patch("asta.papers.get.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_paper.return_value = mock_paper
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli, ["papers", "get", "ARXIV:2005.14165", "--format", "text"]
            )

        assert result.exit_code == 0
        assert "Title: Test Paper" in result.output
        assert "Year: 2024" in result.output
        assert "Authors: John Doe" in result.output


class TestPapersSearch:
    """Test 'asta papers search' command."""

    def test_search_help(self, runner):
        """Test papers search command help."""
        result = runner.invoke(cli, ["papers", "search", "--help"])
        assert result.exit_code == 0
        assert "Search for papers by keyword" in result.output

    def test_search_missing_query(self, runner):
        """Test papers search without query."""
        result = runner.invoke(cli, ["papers", "search"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output

    def test_search_json_format(self, runner):
        """Test papers search with JSON output."""
        mock_result = {
            "total": 2,
            "data": [
                {"paperId": "1", "title": "Paper 1", "year": 2024},
                {"paperId": "2", "title": "Paper 2", "year": 2023},
            ],
        }

        with patch("asta.papers.search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.search_papers.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(cli, ["papers", "search", "test query"])

        assert result.exit_code == 0
        assert "Paper 1" in result.output
        assert "Paper 2" in result.output

    def test_search_with_year_filter(self, runner):
        """Test papers search with year filter."""
        mock_result = {"total": 0, "data": []}

        with patch("asta.papers.search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.search_papers.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli, ["papers", "search", "test query", "--year", "2023-"]
            )

        assert result.exit_code == 0
        mock_instance.search_papers.assert_called_once()
        call_args = mock_instance.search_papers.call_args
        assert call_args[1]["year"] == "2023-"


class TestPapersCitations:
    """Test 'asta papers citations' command."""

    def test_citations_help(self, runner):
        """Test papers citations command help."""
        result = runner.invoke(cli, ["papers", "citations", "--help"])
        assert result.exit_code == 0
        assert "Get papers that cite a given paper" in result.output

    def test_citations_json_format(self, runner):
        """Test papers citations with JSON output."""
        mock_result = {
            "data": [
                {
                    "citingPaper": {
                        "paperId": "1",
                        "title": "Citing Paper 1",
                        "year": 2024,
                    }
                },
            ],
        }

        with patch("asta.papers.citations.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_paper_citations.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(cli, ["papers", "citations", "ARXIV:2005.14165"])

        assert result.exit_code == 0
        assert "Citing Paper 1" in result.output


class TestPapersAuthor:
    """Test 'asta papers author' commands."""

    def test_author_help(self, runner):
        """Test papers author subcommand help."""
        result = runner.invoke(cli, ["papers", "author", "--help"])
        assert result.exit_code == 0
        assert "Author-related commands" in result.output
        assert "search" in result.output
        assert "papers" in result.output

    def test_author_search_help(self, runner):
        """Test author search command help."""
        result = runner.invoke(cli, ["papers", "author", "search", "--help"])
        assert result.exit_code == 0
        assert "Search for authors by name" in result.output

    def test_author_search(self, runner):
        """Test author search command."""
        mock_result = {
            "data": [
                {
                    "authorId": "123",
                    "name": "John Doe",
                    "paperCount": 50,
                    "citationCount": 1000,
                },
            ],
        }

        with patch("asta.papers.author.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.search_author.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(cli, ["papers", "author", "search", "John Doe"])

        assert result.exit_code == 0
        assert "John Doe" in result.output

    def test_author_papers_help(self, runner):
        """Test author papers command help."""
        result = runner.invoke(cli, ["papers", "author", "papers", "--help"])
        assert result.exit_code == 0
        assert "Get papers by an author" in result.output

    def test_author_papers(self, runner):
        """Test author papers command."""
        mock_result = {
            "data": [
                {
                    "paper": {
                        "paperId": "1",
                        "title": "Author's Paper",
                        "year": 2024,
                    }
                },
            ],
        }

        with patch("asta.papers.author.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_author_papers.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(cli, ["papers", "author", "papers", "123"])

        assert result.exit_code == 0
        assert "Author's Paper" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
