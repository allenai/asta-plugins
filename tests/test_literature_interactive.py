"""Tests for the paper-finder ``asta literature interactive`` Click command.

Generic runner-level e2e (single-turn, multi-turn, failed-terminal, HTTP error)
lives in ``test_a2a_interactive.py``. Here we only verify that the paper-finder
skill wires its own callbacks (``parse_artifacts``, ``_build_summary``, the Click
shell) on top correctly.
"""

import json

import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.literature.interactive import _build_summary
from asta.literature.models import LiteratureSearchResult, Paper
from tests._a2a_fixtures import (
    FakeA2AServer,
    artifact_update_event,
    initial_task_event,
    terminal_event,
    working_step_event,
)
from tests._v4_fixtures import v4_paper, v4_search_result


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def _stub_resolver_env(monkeypatch):
    monkeypatch.setenv("ASTA_PAPER_FINDER_A2A_URL", "http://test-server")
    monkeypatch.delenv("ASTA_A2A_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)


def test_e2e_paper_finder_writes_literature_search_result(runner, tmp_path):
    """Smoke that the paper-finder skill plumbing is wired correctly: Click
    parses the args, the runner streams the bare skill input to ``/api/4/a2a``,
    ``parse_artifacts`` translates the v4 artifact into a
    ``LiteratureSearchResult``, and the JSON ends up on disk."""
    out = tmp_path / "results.json"
    events = [
        initial_task_event(),
        working_step_event("Searching"),
        artifact_update_event(v4_search_result([v4_paper()])),
        terminal_event("TASK_STATE_COMPLETED", "Found 1 paper."),
    ]
    with FakeA2AServer(events=events) as server:
        result = runner.invoke(
            cli,
            ["literature", "interactive", "transformer survey", "-o", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert server.urls == ["http://test-server/api/4/a2a"]
    assert server.requests[0]["params"]["message"]["parts"] == [
        {
            "data": {
                "query": "transformer survey",
                "operation_mode": "infer",
                "result": {"preset": "full"},
            }
        }
    ]
    data = json.loads(out.read_text())
    assert data["query"] == "transformer survey"
    assert data["thread_id"] == "thrd:abc"
    assert data["narrative"] == "Found 1 paper."
    [paper] = data["results"]
    assert paper["corpusId"] == 13756489
    assert paper["title"] == "Attention Is All You Need"
    assert paper["citationContexts"][0]["sourceCorpusId"] == 999


def test_build_summary_shape_and_narrative_handling():
    """``_build_summary`` produces the per-turn ``summary`` dict embedded in
    DIR/index.json. The e2e covers a typical narrative; here we lock the shape
    and the corner cases (long narrative passes through, absent → ``None``)."""
    result = LiteratureSearchResult(
        query="hi",
        results=[
            Paper.model_validate(
                {"corpusId": str(i), "title": f"P{i}", "relevanceScore": 0.5}
            )
            for i in range(4)
        ],
    )
    assert _build_summary(result, "Done.", mode="fast") == {
        "query": "hi",
        "mode": "fast",
        "narrative": "Done.",
        "paper_count": 4,
    }
    long_narrative = "x" * 5000
    assert (
        _build_summary(result, long_narrative, mode="infer")["narrative"]
        == long_narrative
    )
    assert _build_summary(result, None, mode="infer")["narrative"] is None
