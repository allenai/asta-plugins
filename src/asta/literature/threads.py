"""Thread state management and CLI commands for literature sessions.

Sessions are stored under SESSIONS_DIR as human-readable folders::

    ~/.asta/literature/sessions/
        2026-03-09-143052-poetry-translation/
            thread.json
            results-01-poetry-translation.json
            results-02-focus-on-llms.json
            exports/
                results.bib

An ``index.json`` at the root maps thread UUIDs to session slugs for O(1) lookup.
"""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import click

from asta.literature.models import ThreadState, Turn

SESSIONS_DIR = Path.home() / ".asta" / "literature" / "sessions"
INDEX_PATH = SESSIONS_DIR / "index.json"


# -- private helpers --


def _ensure_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a lowercase URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len]


def _load_index() -> dict[str, str]:
    """Load the thread_id → session_slug index."""
    if INDEX_PATH.exists():
        with open(INDEX_PATH) as f:
            return json.load(f)
    return {}


def _save_index(index: dict[str, str]) -> None:
    _ensure_dir()
    tmp = INDEX_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(index, f, indent=2)
    os.rename(tmp, INDEX_PATH)


def _index_add(thread_id: str, slug: str) -> None:
    index = _load_index()
    index[thread_id] = slug
    _save_index(index)


# -- public: paths and naming --


def session_dir(slug: str) -> Path:
    """Return the session directory for a given slug."""
    return SESSIONS_DIR / slug


def make_session_slug(query: str) -> str:
    """Create a unique human-readable session folder name from a query.

    Format: ``YYYY-MM-DD-HHMMSS-<query-slug>``
    """
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return f"{timestamp}-{_slugify(query)}"


def results_filename(turn_number: int, message: str) -> str:
    """Build a human-readable results filename for a turn."""
    slug = _slugify(message, max_len=40)
    return f"results-{turn_number:02d}-{slug}.json"


def resolve_session(thread_id: str) -> Path:
    """Resolve a thread_id to its session directory. Raises FileNotFoundError."""
    index = _load_index()
    slug = index.get(thread_id)
    if not slug:
        raise FileNotFoundError(f"No session found for thread: {thread_id}")
    return session_dir(slug)


def thread_path(thread_id: str) -> Path:
    """Return the thread.json path for a given thread_id."""
    return resolve_session(thread_id) / "thread.json"


# -- public: state persistence --


def save_thread_state(state: ThreadState) -> Path:
    """Save thread state atomically to its session directory."""
    d = session_dir(state.session_slug)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "thread.json"
    tmp_path = path.with_suffix(".tmp")
    data = state.model_dump(mode="json")
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(tmp_path, path)
    _index_add(state.thread_id, state.session_slug)
    return path


def save_results(session_slug: str, turn_number: int, message: str, data: dict) -> Path:
    """Save a results JSON file into the session directory."""
    d = session_dir(session_slug)
    d.mkdir(parents=True, exist_ok=True)
    filename = results_filename(turn_number, message)
    path = d / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def load_thread_state(thread_id: str) -> ThreadState:
    """Load thread state from disk by thread_id."""
    path = thread_path(thread_id)
    with open(path) as f:
        data = json.load(f)
    return ThreadState.model_validate(data)


def list_threads() -> list[dict]:
    """Return summary of each session (slug, thread_id, query, turns, count, timestamp)."""
    _ensure_dir()
    summaries = []
    for p in sorted(
        SESSIONS_DIR.glob("*/thread.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    ):
        try:
            with open(p) as f:
                data = json.load(f)
            first_query = data["turns"][0]["input"] if data.get("turns") else ""
            summaries.append(
                {
                    "session": p.parent.name,
                    "thread_id": data["thread_id"],
                    "query": first_query,
                    "turns": len(data.get("turns", [])),
                    "papers": len(data.get("current_results", [])),
                    "updated_at": data.get("updated_at", ""),
                }
            )
        except (json.JSONDecodeError, KeyError):
            continue
    return summaries


def update_thread_turn(
    thread_id: str,
    turn: Turn,
    results: list,
) -> ThreadState:
    """Add a turn and update thread state."""
    state = load_thread_state(thread_id)
    state.turns.append(turn)
    state.current_results = results
    state.updated_at = datetime.now(UTC).isoformat()
    save_thread_state(state)
    return state


def create_initial_state(
    thread_id: str,
    widget_id: str,
    query: str,
    results: list,
    user_id: str = "",
) -> ThreadState:
    """Create and save the initial thread state after a find command."""
    now = datetime.now(UTC).isoformat()
    slug = make_session_slug(query)
    state = ThreadState(
        thread_id=thread_id,
        widget_id=widget_id,
        session_slug=slug,
        user_id=user_id,
        created_at=now,
        updated_at=now,
        turns=[
            Turn(
                turn_number=1,
                type="search",
                input=query,
                timestamp=now,
                result_count=len(results),
            )
        ],
        current_results=results,
        errors=[],
    )
    save_thread_state(state)
    return state


# -- CLI helpers --


def require_thread_state(thread_id: str) -> ThreadState:
    """Load thread state or raise ClickException if not found."""
    try:
        return load_thread_state(thread_id)
    except FileNotFoundError:
        raise click.ClickException(f"Thread not found: {thread_id}")


def format_paper_line(index: int, paper: dict) -> str:
    """Format a paper as a numbered one-liner for CLI display."""
    authors = paper.get("authors", [])
    first_author = authors[0].get("name", "Unknown") if authors else "Unknown"
    year = paper.get("year", "")
    title = paper.get("title", "Untitled")
    return f'  {index}. "{title}" - {first_author}, {year}'


# -- CLI commands --


@click.command("threads")
def threads_list():
    """List all literature search sessions.

    Shows session name, query, number of turns, paper count, and last update.
    """
    items = list_threads()
    if not items:
        click.echo("No sessions found.")
        return

    click.echo(f"{'Session':<45} {'Turns':>5} {'Papers':>7} {'Updated':<20}")
    for t in items:
        session = t["session"]
        if len(session) > 42:
            session = session[:42] + "..."
        updated = t["updated_at"][:19].replace("T", " ") if t["updated_at"] else ""
        click.echo(f"{session:<45} {t['turns']:>5} {t['papers']:>7} {updated:<20}")


@click.command()
@click.argument("thread_id")
@click.option("--full", is_flag=True, help="Show complete results with all metadata")
def show(thread_id: str, full: bool):
    """Show details of a specific thread.

    Displays query history and top results. Use --full for complete metadata.
    """
    state = require_thread_state(thread_id)

    if full:
        click.echo(json.dumps(state.model_dump(mode="json"), indent=2))
        return

    sess_dir = session_dir(state.session_slug)

    click.echo(f"Thread: {state.thread_id}")
    click.echo(f"Session: {sess_dir}")
    click.echo(f"Created: {state.created_at}")
    click.echo(f"Updated: {state.updated_at}")
    click.echo()

    click.echo("Turns:")
    for t in state.turns:
        click.echo(
            f"  {t.turn_number}. [{t.type}] {t.input} ({t.result_count} results)"
        )

    click.echo()
    click.echo(f"Current results: {len(state.current_results)} papers")
    for i, p in enumerate(state.current_results[:5], 1):
        click.echo(format_paper_line(i, p))

    if len(state.current_results) > 5:
        click.echo(f"  ... and {len(state.current_results) - 5} more")

    click.echo()
    click.echo(f"Session: {sess_dir}", err=True)
