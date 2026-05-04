"""Persisted thread state for ``asta literature interactive``.

When the user passes ``--thread-dir DIR``, every turn writes its artifact under
DIR with a turn-index suffix and appends a metadata entry to ``DIR/index.json``.
That index lets the CLI auto-resume the conversation's ``thread_id`` and lets
a human (or skill) reconstruct turn order without inspecting each artifact.

Index schema::

    {
      "thread_id": "thrd:abc",
      "created_at": "2026-05-04T10:00:00+00:00",
      "updated_at": "2026-05-04T10:30:00+00:00",
      "turns": [
        {
          "turn": 1,
          "ts": "2026-05-04T10:00:00+00:00",
          "query": "...",
          "mode": "fast",
          "narrative_excerpt": "first 200 chars",
          "paper_count": 32,
          "file": "transformer-survey.001.json"
        }
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INDEX_FILENAME = "index.json"
TURN_PAD = 3  # zero-padded turn index width
NARRATIVE_EXCERPT_MAX = 200


@dataclass
class TurnEntry:
    turn: int
    ts: str
    query: str
    mode: str
    narrative_excerpt: str | None
    paper_count: int
    file: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "ts": self.ts,
            "query": self.query,
            "mode": self.mode,
            "narrative_excerpt": self.narrative_excerpt,
            "paper_count": self.paper_count,
            "file": self.file,
        }


@dataclass
class ThreadState:
    thread_id: str | None
    created_at: str
    updated_at: str
    turns: list[TurnEntry] = field(default_factory=list)

    @classmethod
    def fresh(cls, thread_id: str | None = None) -> ThreadState:
        now = _now_iso()
        return cls(thread_id=thread_id, created_at=now, updated_at=now, turns=[])

    def next_turn_index(self) -> int:
        return (self.turns[-1].turn if self.turns else 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turns": [t.to_dict() for t in self.turns],
        }


def index_path(thread_dir: Path) -> Path:
    return thread_dir / INDEX_FILENAME


def load_thread_state(thread_dir: Path) -> ThreadState | None:
    """Read ``index.json`` if present. Returns None when the dir is fresh.

    Raises ValueError when the index file exists but is not parseable — better
    to surface a corrupt-state error than to silently start a new thread.
    """
    p = index_path(thread_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"thread index at {p} is unreadable: {e}") from e
    turns_raw = data.get("turns") or []
    turns = [
        TurnEntry(
            turn=int(t["turn"]),
            ts=str(t["ts"]),
            query=str(t.get("query", "")),
            mode=str(t.get("mode", "")),
            narrative_excerpt=t.get("narrative_excerpt"),
            paper_count=int(t.get("paper_count", 0)),
            file=str(t["file"]),
        )
        for t in turns_raw
    ]
    return ThreadState(
        thread_id=data.get("thread_id"),
        created_at=str(data.get("created_at") or _now_iso()),
        updated_at=str(data.get("updated_at") or _now_iso()),
        turns=turns,
    )


def save_thread_state(thread_dir: Path, state: ThreadState) -> None:
    thread_dir.mkdir(parents=True, exist_ok=True)
    state.updated_at = _now_iso()
    index_path(thread_dir).write_text(json.dumps(state.to_dict(), indent=2))


def turn_filename(output_basename: str, turn: int) -> str:
    """Insert a zero-padded turn index before the file extension.

    ``transformer-survey.json`` + turn 2 → ``transformer-survey.002.json``.
    Files without an extension get the suffix at the end (``foo`` → ``foo.002``).
    """
    p = Path(output_basename)
    suffix_n = f".{turn:0{TURN_PAD}d}"
    if p.suffix:
        return f"{p.stem}{suffix_n}{p.suffix}"
    return f"{p.name}{suffix_n}"


def make_turn_entry(
    *,
    turn: int,
    query: str,
    mode: str,
    narrative: str | None,
    paper_count: int,
    file: str,
) -> TurnEntry:
    excerpt: str | None = None
    if narrative:
        excerpt = narrative[:NARRATIVE_EXCERPT_MAX]
    return TurnEntry(
        turn=turn,
        ts=_now_iso(),
        query=query,
        mode=mode,
        narrative_excerpt=excerpt,
        paper_count=paper_count,
        file=file,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
