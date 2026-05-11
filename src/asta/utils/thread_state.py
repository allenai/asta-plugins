"""Persisted thread state for ``--thread-dir`` style A2A interactive sessions.

On-disk schema (``DIR/index.json``)::

    {
      "thread_id": "thrd:abc",
      "created_at": "...",
      "updated_at": "...",
      "turns": [
        {"turn": 1, "ts": "...", "file": "transformer-survey.001.json",
         "summary": {"query": "...", "mode": "fast", "narrative": "...", "paper_count": 32}}
      ]
    }

The ``summary`` blob is skill-defined; everything else is cross-cutting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

INDEX_FILENAME = "index.json"
TURN_PAD = 3


@dataclass(slots=True)
class TurnEntry:
    turn: int
    ts: str
    file: str
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "ts": self.ts,
            "file": self.file,
            "summary": dict(self.summary),
        }


@dataclass(slots=True)
class ThreadState:
    thread_id: str | None
    created_at: str
    updated_at: str
    turns: list[TurnEntry] = field(default_factory=list)

    @classmethod
    def fresh(cls, thread_id: str | None = None) -> Self:
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
    """Returns ``None`` if no index, raises ``ValueError`` if it exists but is corrupt."""
    p = index_path(thread_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"thread index at {p} is unreadable: {e}") from e
    turns = [
        TurnEntry(
            turn=int(t["turn"]),
            ts=str(t["ts"]),
            file=str(t["file"]),
            summary=dict(t.get("summary") or {}),
        )
        for t in (data.get("turns") or [])
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
    """``foo.json`` + turn 2 → ``foo.002.json``; ``foo`` + 2 → ``foo.002``."""
    p = Path(output_basename)
    suffix_n = f".{turn:0{TURN_PAD}d}"
    return f"{p.stem}{suffix_n}{p.suffix}" if p.suffix else f"{p.name}{suffix_n}"


def make_turn_entry(*, turn: int, file: str, summary: dict[str, Any]) -> TurnEntry:
    return TurnEntry(turn=turn, ts=_now_iso(), file=file, summary=dict(summary))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
