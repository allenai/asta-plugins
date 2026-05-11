"""Tests for the paper-finder ``asta literature interactive`` Click command.

Generic runner-level e2e (single-turn, multi-turn, failed-terminal, HTTP error)
lives in ``test_a2a_interactive.py``. Here we only verify that the paper-finder
skill wires its own callbacks (``parse_artifact``, ``_build_summary``, the Click
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
    parses the args, the runner streams, ``parse_artifact`` translates the
    paper-finder-shaped artifact into a ``LiteratureSearchResult``, and the
    JSON ends up on disk with the right fields."""
    out = tmp_path / "results.json"
    paper_finder_artifact = {
        "schemaVersion": "1",
        "subtype": "paper-finder-search-result",
        "entities": {
            "ent_001": {
                "id": "ent_001",
                "type": "PAPER",
                "displayLabel": "Foo",
                "s2Metadata": {
                    "title": "Foo: A Paper",
                    "year": 2024,
                    "venue": "NeurIPS",
                    "corpusId": "12345",
                    "authors": [{"name": "Alice", "authorId": "a1"}],
                },
                "url": "https://s2/12345",
                "relevanceScore": 0.91,
            }
        },
    }
    events = [
        initial_task_event(),
        working_step_event("Searching"),
        artifact_update_event(paper_finder_artifact),
        terminal_event("TASK_STATE_COMPLETED", "Found 1 paper."),
    ]
    with FakeA2AServer(events=events):
        result = runner.invoke(
            cli,
            ["literature", "interactive", "transformer survey", "-o", str(out)],
        )

    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data["query"] == "transformer survey"
    assert data["thread_id"] == "thrd:abc"
    assert data["narrative"] == "Found 1 paper."
    # parse_artifact translated the wire artifact into the LiteratureSearchResult shape.
    assert data["results"][0]["corpusId"] == 12345
    assert data["results"][0]["title"] == "Foo: A Paper"


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
