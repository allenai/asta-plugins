"""Tests for followup, show, threads, and export CLI commands."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.literature.models import ThreadState, Turn
from asta.literature.threads import save_thread_state


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sessions_dir(tmp_path):
    with patch("asta.literature.threads.SESSIONS_DIR", tmp_path):
        with patch("asta.literature.threads.INDEX_PATH", tmp_path / "index.json"):
            yield tmp_path


def _save_sample_thread(
    sessions_dir, thread_id="test-thread", session_slug="2026-03-05-protein-folding"
):
    state = ThreadState(
        thread_id=thread_id,
        widget_id="widget-123",
        session_slug=session_slug,
        created_at="2026-03-05T10:00:00Z",
        updated_at="2026-03-05T10:00:00Z",
        turns=[
            Turn(
                turn_number=1,
                type="search",
                input="protein folding",
                timestamp="2026-03-05T10:00:00Z",
                result_count=3,
            )
        ],
        current_results=[
            {
                "corpusId": 1,
                "title": "Paper One",
                "year": 2024,
                "authors": [{"name": "Alice", "authorId": "a1"}],
                "venue": "NeurIPS",
                "relevanceScore": 0.9,
                "citationCount": 10,
            },
            {
                "corpusId": 2,
                "title": "Paper Two",
                "year": 2023,
                "authors": [{"name": "Bob", "authorId": "b2"}],
                "venue": "ICML",
                "relevanceScore": 0.8,
                "citationCount": 5,
            },
            {
                "corpusId": 3,
                "title": "Paper Three",
                "year": 2024,
                "authors": [],
                "venue": "Nature",
                "relevanceScore": 0.7,
                "citationCount": 20,
            },
        ],
        errors=[],
    )
    save_thread_state(state)
    return state


class TestFollowupCommand:
    def test_followup_help(self, runner):
        result = runner.invoke(cli, ["literature", "followup", "--help"])
        assert result.exit_code == 0
        assert "Send a follow-up MESSAGE" in result.output

    def test_followup_thread_not_found(self, runner, sessions_dir):
        result = runner.invoke(
            cli, ["literature", "followup", "nonexistent", "feedback"]
        )
        assert result.exit_code != 0
        assert "Thread not found" in result.output

    def test_followup_success(self, runner, sessions_dir):
        _save_sample_thread(sessions_dir)

        mock_result = {
            "thread_id": "test-thread",
            "widget_id": "widget-new",
            "widget": {
                "results": [
                    {
                        "corpusId": 10,
                        "title": "Followup Paper",
                        "year": 2024,
                        "authors": [{"name": "Carol"}],
                    }
                ]
            },
            "paper_count": 1,
        }

        with patch("asta.literature.followup.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.send_followup.return_value = mock_result
            MockFinder.return_value = mock_instance

            result = runner.invoke(
                cli, ["literature", "followup", "test-thread", "focus on 2024"]
            )

        assert result.exit_code == 0
        assert "updated (turn 2)" in result.output
        assert "Papers: 1 (was 3)" in result.output
        assert "Followup Paper" in result.output


class TestThreadsCommand:
    def test_threads_empty(self, runner, sessions_dir):
        result = runner.invoke(cli, ["literature", "threads"])
        assert result.exit_code == 0
        assert "No sessions found" in result.output

    def test_threads_lists(self, runner, sessions_dir):
        _save_sample_thread(sessions_dir, "thread-a", "2026-03-05-query-a")
        _save_sample_thread(sessions_dir, "thread-b", "2026-03-05-query-b")

        result = runner.invoke(cli, ["literature", "threads"])
        assert result.exit_code == 0
        assert "2026-03-05-query-a" in result.output
        assert "2026-03-05-query-b" in result.output


class TestShowCommand:
    def test_show_not_found(self, runner, sessions_dir):
        result = runner.invoke(cli, ["literature", "show", "nonexistent"])
        assert result.exit_code != 0
        assert "Thread not found" in result.output

    def test_show_summary(self, runner, sessions_dir):
        _save_sample_thread(sessions_dir)
        result = runner.invoke(cli, ["literature", "show", "test-thread"])
        assert result.exit_code == 0
        assert "test-thread" in result.output
        assert "Paper One" in result.output
        assert "protein folding" in result.output

    def test_show_full(self, runner, sessions_dir):
        _save_sample_thread(sessions_dir)
        result = runner.invoke(cli, ["literature", "show", "test-thread", "--full"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["thread_id"] == "test-thread"
        assert len(data["current_results"]) == 3


class TestExportCommand:
    def test_export_json(self, runner, sessions_dir):
        _save_sample_thread(sessions_dir)
        result = runner.invoke(
            cli, ["literature", "export", "test-thread", "--format", "json"]
        )
        assert result.exit_code == 0
        assert "Exported 3 papers" in result.output

    def test_export_csv(self, runner, sessions_dir):
        _save_sample_thread(sessions_dir)
        result = runner.invoke(
            cli, ["literature", "export", "test-thread", "--format", "csv"]
        )
        assert result.exit_code == 0
        assert "Exported 3 papers" in result.output
        csv_file = (
            sessions_dir / "2026-03-05-protein-folding" / "exports" / "results.csv"
        )
        assert csv_file.exists()
        content = csv_file.read_text()
        assert "Paper One" in content

    def test_export_bibtex(self, runner, sessions_dir):
        _save_sample_thread(sessions_dir)
        result = runner.invoke(
            cli, ["literature", "export", "test-thread", "--format", "bibtex"]
        )
        assert result.exit_code == 0
        assert "Exported 3 papers" in result.output
        bib_file = (
            sessions_dir / "2026-03-05-protein-folding" / "exports" / "results.bib"
        )
        assert bib_file.exists()
        content = bib_file.read_text()
        assert "@article" in content
        assert "Paper One" in content

    def test_export_not_found(self, runner, sessions_dir):
        result = runner.invoke(
            cli, ["literature", "export", "nonexistent", "--format", "json"]
        )
        assert result.exit_code != 0
        assert "Thread not found" in result.output
