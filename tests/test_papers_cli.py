"""Tests for the papers CLI commands."""

import os
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


class TestPapersGetCutoff:
    """``ASTA_PUBLICATION_DATE_RANGE`` upper bound rejects post-cutoff
    papers with a cutoff-disclosing error that matches astabench MCP's
    ``_error_if_recent_papers_toplevel`` verbatim — keeps eval scores
    comparable across the two agent-facing surfaces."""

    def _run(self, runner, mock_paper, env):
        with patch("asta.papers.get.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_paper.return_value = mock_paper
            MockClient.return_value = mock_instance
            with patch.dict("os.environ", env, clear=False):
                result = runner.invoke(cli, ["papers", "get", "ARXIV:fake"])
        return result, mock_instance

    def test_paper_within_cutoff_passes_through(self, runner):
        result, _ = self._run(
            runner,
            {"paperId": "ok", "title": "Old Paper", "publicationDate": "2024-01-01"},
            {"ASTA_PUBLICATION_DATE_RANGE": ":2024-10-17"},
        )
        assert result.exit_code == 0
        assert "Old Paper" in result.output

    def test_post_cutoff_paper_is_rejected(self, runner):
        result, _ = self._run(
            runner,
            {"paperId": "leak", "title": "Leak Paper", "publicationDate": "2025-04-01"},
            {"ASTA_PUBLICATION_DATE_RANGE": ":2024-10-17"},
        )
        assert result.exit_code != 0
        assert "newer than the date cutoff of 2024-10-17" in result.output
        # Title and other paper metadata still aren't exposed.
        assert "Leak Paper" not in result.output

    def test_undated_paper_is_rejected_when_cutoff_active(self, runner):
        # No publicationDate and no year — we can't prove the paper
        # predates the cutoff, so reject it.
        result, _ = self._run(
            runner,
            {"paperId": "?", "title": "Mystery"},
            {"ASTA_PUBLICATION_DATE_RANGE": ":2024-10-17"},
        )
        assert result.exit_code != 0
        assert "newer than the date cutoff" in result.output
        assert "Mystery" not in result.output

    def test_year_fallback_admits_paper_at_year_end(self, runner):
        # Year-only response: treat as end-of-year for cutoff purposes,
        # matching astabench's _filter_one_paper approximation.
        result, _ = self._run(
            runner,
            {"paperId": "ok", "title": "Year Only", "year": 2024},
            {"ASTA_PUBLICATION_DATE_RANGE": ":2024-12-31"},
        )
        assert result.exit_code == 0
        assert "Year Only" in result.output

    def test_year_range_upper_bound(self, runner):
        result, _ = self._run(
            runner,
            {"paperId": "leak", "title": "Future", "publicationDate": "2025-06-01"},
            {"ASTA_PUBLICATION_DATE_RANGE": "2020-2024"},
        )
        assert result.exit_code != 0
        assert "Future" not in result.output

    def test_open_upper_bound_disables_enforcement(self, runner):
        # "2020-" has no upper bound; cutoff check is inactive.
        result, _ = self._run(
            runner,
            {"paperId": "ok", "title": "Recent", "publicationDate": "2099-01-01"},
            {"ASTA_PUBLICATION_DATE_RANGE": "2020-"},
        )
        assert result.exit_code == 0
        assert "Recent" in result.output

    def test_no_env_passes_through(self, runner):
        # Sanity: the cutoff path is dormant when the env var is unset.
        with patch("asta.papers.get.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_paper.return_value = {
                "paperId": "x",
                "title": "Anything",
                "publicationDate": "2099-01-01",
            }
            MockClient.return_value = mock_instance
            with patch.dict("os.environ", {}, clear=False):
                os.environ.pop("ASTA_PUBLICATION_DATE_RANGE", None)
                result = runner.invoke(cli, ["papers", "get", "ARXIV:fake"])
        assert result.exit_code == 0
        assert "Anything" in result.output

    def test_fields_augmented_when_cutoff_active(self, runner):
        # Caller asked for just "title"; cutoff enforcement requires
        # publicationDate/year, so the request must include them.
        with patch("asta.papers.get.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_paper.return_value = {
                "paperId": "ok",
                "title": "T",
                "publicationDate": "2024-01-01",
            }
            MockClient.return_value = mock_instance
            with patch.dict(
                "os.environ", {"ASTA_PUBLICATION_DATE_RANGE": ":2024-10-17"}
            ):
                result = runner.invoke(
                    cli, ["papers", "get", "ARXIV:fake", "--fields", "title"]
                )
        assert result.exit_code == 0
        sent_fields = mock_instance.get_paper.call_args[1]["fields"]
        assert "publicationDate" in sent_fields
        assert "year" in sent_fields


class TestSnippetSearchInsertedBeforeEnv:
    """``ASTA_INSERTED_BEFORE`` provides a CLI-wide default for the
    ``--inserted-before`` flag on snippet-search. Lets the harness pin
    snippet queries to a server-side cutoff without per-invocation flags."""

    def test_env_used_when_flag_absent(self, runner):
        with patch("asta.papers.snippet_search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.snippet_search.return_value = {"data": []}
            MockClient.return_value = mock_instance
            with patch.dict("os.environ", {"ASTA_INSERTED_BEFORE": "2024-10-17"}):
                result = runner.invoke(cli, ["papers", "snippet-search", "q"])
        assert result.exit_code == 0
        assert (
            mock_instance.snippet_search.call_args[1]["inserted_before"] == "2024-10-17"
        )

    def test_flag_overrides_env(self, runner):
        with patch("asta.papers.snippet_search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.snippet_search.return_value = {"data": []}
            MockClient.return_value = mock_instance
            with patch.dict("os.environ", {"ASTA_INSERTED_BEFORE": "2024-10-17"}):
                result = runner.invoke(
                    cli,
                    [
                        "papers",
                        "snippet-search",
                        "q",
                        "--inserted-before",
                        "2023-01-01",
                    ],
                )
        assert result.exit_code == 0
        assert (
            mock_instance.snippet_search.call_args[1]["inserted_before"] == "2023-01-01"
        )


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

    def test_search_with_date_filter(self, runner):
        """Test papers search with date filter."""
        mock_result = {"total": 0, "data": []}

        with patch("asta.papers.search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.search_papers.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli, ["papers", "search", "test query", "--date", "2023-"]
            )

        assert result.exit_code == 0
        mock_instance.search_papers.assert_called_once()
        call_args = mock_instance.search_papers.call_args
        assert call_args[1]["publication_date_or_year"] == "2023-"


class TestPapersSnippetSearch:
    """Test 'asta papers snippet-search' command."""

    def test_snippet_search_help(self, runner):
        """Test snippet-search command help."""
        result = runner.invoke(cli, ["papers", "snippet-search", "--help"])
        assert result.exit_code == 0
        assert "full-text snippet matching" in result.output

    def test_snippet_search_missing_query(self, runner):
        """Test snippet-search without query."""
        result = runner.invoke(cli, ["papers", "snippet-search"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output

    def test_snippet_search_json_format(self, runner):
        """Test snippet-search with JSON output."""
        mock_result = {
            "data": [
                {
                    "paper": {
                        "corpusId": "123",
                        "title": "Snippet Paper",
                        "authors": [{"name": "Author A"}],
                    },
                    "score": 0.95,
                    "snippet": {
                        "text": "This is a matching snippet from the paper body.",
                        "snippetKind": "body",
                    },
                },
            ],
        }

        with patch("asta.papers.snippet_search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.snippet_search.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(cli, ["papers", "snippet-search", "test query"])

        assert result.exit_code == 0
        mock_instance.snippet_search.assert_called_once()
        assert "Snippet Paper" in result.output
        # Default fields should be snippet-appropriate
        call_args = mock_instance.snippet_search.call_args
        assert call_args[1]["fields"] == "snippet.text,snippet.snippetKind"

    def test_snippet_search_text_format(self, runner):
        """Test snippet-search with text output."""
        mock_result = {
            "data": [
                {
                    "paper": {
                        "title": "Snippet Paper",
                        "authors": [{"name": "Author A"}, {"name": "Author B"}],
                    },
                    "score": 0.95,
                    "snippet": {
                        "text": "This is a matching snippet.",
                        "snippetKind": "abstract",
                    },
                },
            ],
        }

        with patch("asta.papers.snippet_search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.snippet_search.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli,
                ["papers", "snippet-search", "test query", "--format", "text"],
            )

        assert result.exit_code == 0
        assert "Snippet Paper" in result.output
        assert "Author A" in result.output
        assert "This is a matching snippet." in result.output
        assert "abstract" in result.output

    def test_snippet_search_custom_fields(self, runner):
        """Test snippet-search with explicit --fields."""
        mock_result = {"data": []}

        with patch("asta.papers.snippet_search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.snippet_search.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli,
                [
                    "papers",
                    "snippet-search",
                    "test query",
                    "--fields",
                    "snippet.text",
                ],
            )

        assert result.exit_code == 0
        call_args = mock_instance.snippet_search.call_args
        assert call_args[1]["fields"] == "snippet.text"

    def test_snippet_search_inserted_before(self, runner):
        """Test snippet-search with --inserted-before."""
        mock_result = {"data": []}

        with patch("asta.papers.snippet_search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.snippet_search.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli,
                [
                    "papers",
                    "snippet-search",
                    "test query",
                    "--inserted-before",
                    "2024-01-01",
                ],
            )

        assert result.exit_code == 0
        call_args = mock_instance.snippet_search.call_args
        assert call_args[1]["inserted_before"] == "2024-01-01"

    def test_snippet_search_date_filter(self, runner):
        """Test snippet-search with --date filter."""
        mock_result = {"data": []}

        with patch("asta.papers.snippet_search.SemanticScholarClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.snippet_search.return_value = mock_result
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli,
                ["papers", "snippet-search", "test query", "--date", "2023-"],
            )

        assert result.exit_code == 0
        call_args = mock_instance.snippet_search.call_args
        assert call_args[1]["publication_date_or_year"] == "2023-"


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


class TestSemanticScholarClient:
    """Test SemanticScholarClient initialization and configuration."""

    def test_init_with_explicit_params(self):
        """Test that client initializes with explicit parameters."""
        from asta.papers.client import SemanticScholarClient

        custom_url = "https://custom.semantic.example.com/v1"
        token = "test-access-token-456"
        client = SemanticScholarClient(base_url=custom_url, access_token=token)
        assert client.base_url == custom_url
        assert client.access_token == token
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == f"Bearer {token}"

    def test_init_from_config(self):
        """Test that client loads from config when available."""
        from asta.papers.client import SemanticScholarClient

        with patch("asta.papers.client.get_api_config") as mock_get_api:
            with patch("asta.papers.client.get_access_token") as mock_get_token:
                mock_get_api.return_value = {"base_url": "https://config.url"}
                mock_get_token.return_value = "config-token"

                client = SemanticScholarClient()
                assert client.base_url == "https://config.url"
                assert client.access_token == "config-token"

    def test_init_fails_without_base_url(self):
        """Test that client fails without base_url."""
        from asta.papers.client import SemanticScholarClient

        with patch("asta.papers.client.get_api_config") as mock_get_api:
            with patch("asta.papers.client.get_access_token") as mock_get_token:
                mock_get_api.side_effect = KeyError("Not found")
                mock_get_token.return_value = "test-token"

                with pytest.raises(
                    ValueError, match="No value for apis.semantic_scholar.base_url"
                ):
                    SemanticScholarClient()

    def test_init_fails_without_access_token(self):
        """Test that client fails without access_token."""
        from asta.auth.exceptions import AuthenticationError
        from asta.papers.client import SemanticScholarClient

        with patch("asta.papers.client.get_api_config") as mock_get_api:
            with patch("asta.papers.client.get_access_token") as mock_get_token:
                mock_get_api.return_value = {"base_url": "https://test.url"}
                mock_get_token.side_effect = AuthenticationError(
                    "Not authenticated. Please run 'asta auth login' to authenticate."
                )

                with pytest.raises(
                    AuthenticationError, match="Please run 'asta auth login'"
                ):
                    SemanticScholarClient()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
