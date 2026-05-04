"""Tests for the thread-state index used by `--thread-dir`."""

import json

import pytest

from asta.literature.thread_state import (
    INDEX_FILENAME,
    ThreadState,
    index_path,
    load_thread_state,
    make_turn_entry,
    save_thread_state,
    turn_filename,
)


class TestTurnFilename:
    def test_inserts_index_before_extension(self):
        assert turn_filename("foo.json", 1) == "foo.001.json"
        assert turn_filename("transformer-survey.json", 12) == "transformer-survey.012.json"

    def test_handles_no_extension(self):
        assert turn_filename("foo", 1) == "foo.001"

    def test_uses_last_extension_only(self):
        # `Path.suffix` returns only the trailing extension; this is intentional.
        assert turn_filename("foo.tar.gz", 3) == "foo.tar.003.gz"

    def test_pads_to_three_digits(self):
        assert turn_filename("a.json", 7).split(".")[1] == "007"
        assert turn_filename("a.json", 999).split(".")[1] == "999"


class TestLoadAndSave:
    def test_load_returns_none_when_index_missing(self, tmp_path):
        assert load_thread_state(tmp_path) is None

    def test_save_then_load_roundtrip(self, tmp_path):
        state = ThreadState.fresh(thread_id="thrd:abc")
        state.turns.append(
            make_turn_entry(
                turn=1,
                query="q1",
                mode="fast",
                narrative="here are some papers",
                paper_count=5,
                file="results.001.json",
            )
        )
        save_thread_state(tmp_path, state)

        assert (tmp_path / INDEX_FILENAME).exists()
        loaded = load_thread_state(tmp_path)
        assert loaded is not None
        assert loaded.thread_id == "thrd:abc"
        assert len(loaded.turns) == 1
        assert loaded.turns[0].turn == 1
        assert loaded.turns[0].query == "q1"
        assert loaded.turns[0].paper_count == 5
        assert loaded.turns[0].file == "results.001.json"

    def test_corrupt_index_raises(self, tmp_path):
        index_path(tmp_path).write_text("{not json")
        with pytest.raises(ValueError, match="unreadable"):
            load_thread_state(tmp_path)

    def test_save_creates_directory(self, tmp_path):
        target = tmp_path / "deep" / "nested"
        save_thread_state(target, ThreadState.fresh(thread_id="x"))
        assert (target / INDEX_FILENAME).exists()


class TestNextTurnIndex:
    def test_starts_at_one(self):
        assert ThreadState.fresh().next_turn_index() == 1

    def test_increments_from_last(self):
        state = ThreadState.fresh(thread_id="x")
        state.turns.append(
            make_turn_entry(
                turn=1, query="q", mode="fast", narrative=None, paper_count=0, file="a.001.json"
            )
        )
        state.turns.append(
            make_turn_entry(
                turn=2, query="q", mode="fast", narrative=None, paper_count=0, file="a.002.json"
            )
        )
        assert state.next_turn_index() == 3


class TestMakeTurnEntry:
    def test_truncates_long_narrative(self):
        long_text = "x" * 5000
        entry = make_turn_entry(
            turn=1, query="q", mode="fast", narrative=long_text, paper_count=1, file="r.json"
        )
        assert entry.narrative_excerpt is not None
        assert len(entry.narrative_excerpt) == 200

    def test_omits_excerpt_when_no_narrative(self):
        entry = make_turn_entry(
            turn=1, query="q", mode="fast", narrative=None, paper_count=0, file="r.json"
        )
        assert entry.narrative_excerpt is None


def test_index_json_shape_is_stable(tmp_path):
    """Locks the on-disk schema. Update with intent — downstream tooling reads this."""
    state = ThreadState(
        thread_id="thrd:xyz",
        created_at="2026-05-04T10:00:00+00:00",
        updated_at="2026-05-04T10:30:00+00:00",
    )
    state.turns.append(
        make_turn_entry(
            turn=1,
            query="hello",
            mode="fast",
            narrative="some text",
            paper_count=3,
            file="hello.001.json",
        )
    )
    save_thread_state(tmp_path, state)
    on_disk = json.loads((tmp_path / INDEX_FILENAME).read_text())
    assert set(on_disk.keys()) == {"thread_id", "created_at", "updated_at", "turns"}
    assert set(on_disk["turns"][0].keys()) == {
        "turn",
        "ts",
        "query",
        "mode",
        "narrative_excerpt",
        "paper_count",
        "file",
    }
