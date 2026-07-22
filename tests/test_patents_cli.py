"""Tests for the patent CLI commands."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli


@pytest.fixture
def runner():
    """Provide a Click CLI test runner."""
    return CliRunner()


class TestPatentBasics:
    """Test basic patent CLI wiring."""

    def test_patent_help(self, runner):
        result = runner.invoke(cli, ["patents", "--help"])
        assert result.exit_code == 0
        assert "Patent" in result.output
        assert "search" in result.output
        assert "get" in result.output
        assert "forward-citations" in result.output


class TestPatentSearch:
    """Test 'asta patents search'."""

    def test_search_help(self, runner):
        result = runner.invoke(cli, ["patents", "search", "--help"])
        assert result.exit_code == 0
        assert "BM25" in result.output

    def test_search_missing_query(self, runner):
        result = runner.invoke(cli, ["patents", "search"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output

    def test_search_json(self, runner):
        envelope = {
            "total": 1,
            "offset": 0,
            "data": [{"ucid": "US-10123456-B2", "title": "A Widget"}],
        }
        with patch("asta.patents.search.PatentClient") as MockClient:
            instance = MagicMock()
            instance.search.return_value = envelope
            MockClient.return_value = instance
            result = runner.invoke(cli, ["patents", "search", "widget"])

        assert result.exit_code == 0
        assert json.loads(result.output) == envelope
        instance.search.assert_called_once()
        _, kwargs = instance.search.call_args
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 0

    def test_search_text(self, runner):
        envelope = {
            "total": 1,
            "offset": 0,
            "data": [
                {
                    "ucid": "US-10123456-B2",
                    "title": "A Widget",
                    "assignees": ["Acme Corp"],
                    "publicationDate": "2020-01-01",
                }
            ],
        }
        with patch("asta.patents.search.PatentClient") as MockClient:
            instance = MagicMock()
            instance.search.return_value = envelope
            MockClient.return_value = instance
            result = runner.invoke(
                cli, ["patents", "search", "widget", "--format", "text"]
            )

        assert result.exit_code == 0
        assert "A Widget" in result.output
        assert "US-10123456-B2" in result.output
        assert "Acme Corp" in result.output

    def test_search_passes_options(self, runner):
        with patch("asta.patents.search.PatentClient") as MockClient:
            instance = MagicMock()
            instance.search.return_value = {"data": []}
            MockClient.return_value = instance
            result = runner.invoke(
                cli,
                ["patents", "search", "widget", "--limit", "25", "--offset", "5"],
            )

        assert result.exit_code == 0
        _, kwargs = instance.search.call_args
        assert kwargs["limit"] == 25
        assert kwargs["offset"] == 5


class TestPatentGet:
    """Test 'asta patents get'."""

    def test_get_help(self, runner):
        result = runner.invoke(cli, ["patents", "get", "--help"])
        assert result.exit_code == 0
        assert "UCID" in result.output

    def test_get_missing_ucid(self, runner):
        result = runner.invoke(cli, ["patents", "get"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output

    def test_get_json(self, runner):
        patent = {"ucid": "US-10123456-B2", "title": "A Widget"}
        with patch("asta.patents.get.PatentClient") as MockClient:
            instance = MagicMock()
            instance.get_patent.return_value = patent
            MockClient.return_value = instance
            result = runner.invoke(cli, ["patents", "get", "US-10123456-B2"])

        assert result.exit_code == 0
        assert json.loads(result.output) == patent
        instance.get_patent.assert_called_once()

    def test_get_text(self, runner):
        patent = {
            "ucid": "US-10123456-B2",
            "title": "A Widget",
            "assignees": ["Acme Corp"],
            "inventors": ["Jane Doe"],
            "citedPaperCorpusIds": [111, 222],
            "abstract": "A better widget.",
        }
        with patch("asta.patents.get.PatentClient") as MockClient:
            instance = MagicMock()
            instance.get_patent.return_value = patent
            MockClient.return_value = instance
            result = runner.invoke(
                cli, ["patents", "get", "US-10123456-B2", "--format", "text"]
            )

        assert result.exit_code == 0
        assert "Title: A Widget" in result.output
        assert "UCID: US-10123456-B2" in result.output
        assert "Jane Doe" in result.output
        assert "111, 222" in result.output
        assert "A better widget." in result.output


class TestPatentForwardCitations:
    """Test 'asta patents forward-citations'."""

    def test_help(self, runner):
        result = runner.invoke(cli, ["patents", "forward-citations", "--help"])
        assert result.exit_code == 0
        assert "cite a given paper" in result.output

    def test_requires_int_corpus_id(self, runner):
        result = runner.invoke(cli, ["patents", "forward-citations", "not-a-number"])
        assert result.exit_code != 0

    def test_json(self, runner):
        envelope = {
            "total": 1,
            "offset": 0,
            "data": [{"ucid": "US-10123456-B2", "title": "A Widget"}],
        }
        with patch("asta.patents.forward_citations.PatentClient") as MockClient:
            instance = MagicMock()
            instance.forward_citations.return_value = envelope
            MockClient.return_value = instance
            result = runner.invoke(cli, ["patents", "forward-citations", "215416146"])

        assert result.exit_code == 0
        assert json.loads(result.output) == envelope
        args, kwargs = instance.forward_citations.call_args
        assert args[0] == 215416146


class TestPatentClient:
    """Test PatentClient request building."""

    def _client(self):
        from asta.patents.client import PatentClient

        return PatentClient(base_url="https://api.example.com", access_token="tok")

    def test_search_path_and_params(self):
        client = self._client()
        with patch.object(client, "_request", return_value={"data": []}) as req:
            client.search("widget", fields="ucid,title", limit=200, offset=3)
        path, params = req.call_args[0]
        assert path == "/graph/v1/patent/search"
        assert params["query"] == "widget"
        assert params["limit"] == 100  # clamped to max
        assert params["offset"] == 3

    def test_get_quotes_ucid(self):
        client = self._client()
        with patch.object(client, "_request", return_value={}) as req:
            client.get_patent("US-10123456-B2", fields="ucid,title")
        path = req.call_args[0][0]
        assert path == "/graph/v1/patent/US-10123456-B2"

    def test_forward_citations_path(self):
        client = self._client()
        with patch.object(client, "_request", return_value={"data": []}) as req:
            client.forward_citations(215416146, limit=10, offset=0)
        path = req.call_args[0][0]
        assert path == "/graph/v1/patent/forward-citations/215416146"
