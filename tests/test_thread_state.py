"""Tests for the thread-state index used by ``--thread-dir`` style sessions."""

import json

import pytest

from asta.utils.thread_state import (
    INDEX_FILENAME,
    ThreadState,
    index_path,
    load_thread_state,
    make_turn_entry,
    save_thread_state,
    turn_filename,
)


@pytest.mark.parametrize(
    "basename,turn,expected",
    [
        ("foo.json", 1, "foo.001.json"),                # happy path
        ("foo", 1, "foo.001"),                          # no extension
        ("foo.tar.gz", 3, "foo.tar.003.gz"),            # only the trailing extension
        ("a.json", 999, "a.999.json"),                  # zero-padded width
    ],
)
def test_turn_filename(basename, turn, expected):
    assert turn_filename(basename, turn) == expected


def test_save_then_load_roundtrip(tmp_path):
    """Round-trips both turn ordering and skill-supplied summary blobs, and
    advances ``next_turn_index`` accordingly."""
    state = ThreadState.fresh(thread_id="thrd:abc")
    state.turns.append(
        make_turn_entry(turn=1, file="r.001.json", summary={"q": "first"})
    )
    state.turns.append(
        make_turn_entry(turn=2, file="r.002.json", summary={"q": "second"})
    )
    save_thread_state(tmp_path, state)

    loaded = load_thread_state(tmp_path)
    assert loaded is not None
    assert loaded.thread_id == "thrd:abc"
    assert [t.file for t in loaded.turns] == ["r.001.json", "r.002.json"]
    assert [t.summary["q"] for t in loaded.turns] == ["first", "second"]
    assert loaded.next_turn_index() == 3


def test_load_raises_on_corrupt_index(tmp_path):
    index_path(tmp_path).write_text("{not json")
    with pytest.raises(ValueError, match="unreadable"):
        load_thread_state(tmp_path)


def test_index_json_shape_is_stable(tmp_path):
    """Locks the on-disk schema. Update with intent — downstream tooling reads this."""
    state = ThreadState(
        thread_id="thrd:xyz",
        created_at="2026-05-04T10:00:00+00:00",
        updated_at="2026-05-04T10:30:00+00:00",
    )
    state.turns.append(
        make_turn_entry(turn=1, file="hello.001.json", summary={"query": "hello"})
    )
    save_thread_state(tmp_path, state)

    on_disk = json.loads((tmp_path / INDEX_FILENAME).read_text())
    assert set(on_disk.keys()) == {"thread_id", "created_at", "updated_at", "turns"}
    assert set(on_disk["turns"][0].keys()) == {"turn", "ts", "file", "summary"}
