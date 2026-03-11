"""Tests for thread state management."""

from unittest.mock import patch

import pytest

from asta.literature.models import ThreadState, Turn
from asta.literature.threads import (
    create_initial_state,
    list_threads,
    load_thread_state,
    make_session_slug,
    resolve_session,
    results_filename,
    save_results,
    save_thread_state,
    update_thread_turn,
)


@pytest.fixture
def sessions_dir(tmp_path):
    """Patch SESSIONS_DIR and INDEX_PATH to use a temp directory."""
    with patch("asta.literature.threads.SESSIONS_DIR", tmp_path):
        with patch("asta.literature.threads.INDEX_PATH", tmp_path / "index.json"):
            yield tmp_path


def _make_state(
    thread_id="test-thread-123", session_slug="2026-03-05-test-query", papers=None
):
    if papers is None:
        papers = [{"corpusId": 1, "title": "Paper A"}]
    return ThreadState(
        thread_id=thread_id,
        widget_id="widget-456",
        session_slug=session_slug,
        created_at="2026-03-05T10:00:00Z",
        updated_at="2026-03-05T10:00:00Z",
        turns=[
            Turn(
                turn_number=1,
                type="search",
                input="test query",
                timestamp="2026-03-05T10:00:00Z",
                result_count=len(papers),
            )
        ],
        current_results=papers,
        errors=[],
    )


class TestSessionSlug:
    def test_make_session_slug(self):
        slug = make_session_slug("Poetry Translation with LLMs")
        # Should contain date-time prefix and slugified query
        assert slug.endswith("poetry-translation-with-llms")
        assert len(slug.split("-")) >= 5  # YYYY-MM-DD-HHMMSS-query...

    def test_results_filename(self):
        name = results_filename(1, "poetry translation")
        assert name == "results-01-poetry-translation.json"

    def test_results_filename_truncates(self):
        name = results_filename(2, "a" * 100)
        assert name.startswith("results-02-")
        assert name.endswith(".json")
        assert len(name) <= 60

    def test_make_session_slug_includes_time(self):
        slug = make_session_slug("test query")
        # Format: YYYY-MM-DD-HHMMSS-query-slug
        parts = slug.split("-")
        assert len(parts) >= 4
        # 4th part should be HHMMSS (6 digits)
        assert len(parts[3]) == 6
        assert parts[3].isdigit()


class TestSaveAndLoad:
    def test_save_creates_session_dir(self, sessions_dir):
        state = _make_state()
        path = save_thread_state(state)
        assert path.exists()
        assert path.name == "thread.json"
        assert path.parent.name == "2026-03-05-test-query"

    def test_load_round_trips(self, sessions_dir):
        state = _make_state()
        save_thread_state(state)
        loaded = load_thread_state("test-thread-123")
        assert loaded.thread_id == state.thread_id
        assert loaded.widget_id == state.widget_id
        assert loaded.session_slug == state.session_slug
        assert len(loaded.turns) == 1
        assert loaded.current_results == state.current_results

    def test_load_missing_raises(self, sessions_dir):
        with pytest.raises(FileNotFoundError):
            load_thread_state("nonexistent")

    def test_save_atomic_no_tmp_left(self, sessions_dir):
        state = _make_state()
        save_thread_state(state)
        session = sessions_dir / "2026-03-05-test-query"
        tmp_files = list(session.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_save_overwrites(self, sessions_dir):
        state = _make_state()
        save_thread_state(state)
        state.user_id = "updated-user"
        save_thread_state(state)
        loaded = load_thread_state("test-thread-123")
        assert loaded.user_id == "updated-user"


class TestIndex:
    def test_index_created_on_save(self, sessions_dir):
        state = _make_state()
        save_thread_state(state)
        assert (sessions_dir / "index.json").exists()

    def test_resolve_session(self, sessions_dir):
        state = _make_state()
        save_thread_state(state)
        d = resolve_session("test-thread-123")
        assert d == sessions_dir / "2026-03-05-test-query"

    def test_resolve_missing_raises(self, sessions_dir):
        with pytest.raises(FileNotFoundError):
            resolve_session("nonexistent")


class TestSaveResults:
    def test_saves_to_session(self, sessions_dir):
        state = _make_state()
        save_thread_state(state)
        path = save_results("2026-03-05-test-query", 1, "test query", {"data": True})
        assert path.exists()
        assert path.parent.name == "2026-03-05-test-query"
        assert path.name == "results-01-test-query.json"


class TestListThreads:
    def test_list_empty(self, sessions_dir):
        assert list_threads() == []

    def test_list_multiple(self, sessions_dir):
        save_thread_state(_make_state("thread-a", "2026-03-05-query-a"))
        save_thread_state(_make_state("thread-b", "2026-03-05-query-b"))
        items = list_threads()
        assert len(items) == 2
        ids = {t["thread_id"] for t in items}
        assert ids == {"thread-a", "thread-b"}

    def test_list_returns_summary_fields(self, sessions_dir):
        save_thread_state(_make_state("thread-a", "2026-03-05-query-a"))
        items = list_threads()
        item = items[0]
        assert "session" in item
        assert "thread_id" in item
        assert "query" in item
        assert "turns" in item
        assert "papers" in item
        assert "updated_at" in item


class TestUpdateThreadTurn:
    def test_adds_turn(self, sessions_dir):
        save_thread_state(_make_state())
        new_turn = Turn(
            turn_number=2,
            type="followup",
            input="focus on 2024",
            timestamp="2026-03-05T10:05:00Z",
            result_count=5,
        )
        new_results = [{"corpusId": 2, "title": "Paper B"}]
        state = update_thread_turn("test-thread-123", new_turn, new_results)
        assert len(state.turns) == 2
        assert state.turns[1].input == "focus on 2024"
        assert state.current_results == new_results

    def test_persists_to_disk(self, sessions_dir):
        save_thread_state(_make_state())
        new_turn = Turn(
            turn_number=2,
            type="followup",
            input="narrow",
            timestamp="2026-03-05T10:05:00Z",
            result_count=3,
        )
        update_thread_turn("test-thread-123", new_turn, [])
        loaded = load_thread_state("test-thread-123")
        assert len(loaded.turns) == 2


class TestCreateInitialState:
    def test_creates_and_saves(self, sessions_dir):
        papers = [{"corpusId": 99, "title": "New Paper"}]
        state = create_initial_state(
            thread_id="new-thread",
            widget_id="w-123",
            query="my query",
            results=papers,
        )
        assert state.thread_id == "new-thread"
        assert state.session_slug.endswith("-my-query")
        assert len(state.turns) == 1
        assert state.turns[0].type == "search"
        assert state.turns[0].input == "my query"

        # Verify persisted
        loaded = load_thread_state("new-thread")
        assert loaded.thread_id == "new-thread"

        # Verify session directory exists
        d = resolve_session("new-thread")
        assert d.exists()
        assert (d / "thread.json").exists()
