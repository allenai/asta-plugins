"""Interactive-A2A skill runner: Click options + server/auth resolution +
``--thread-dir`` state + streaming + output writing.

A skill module on top of this is ~50 lines: a Click command with skill-specific
options, an :class:`A2ASkillSpec`, and two callbacks (artifact → result,
optional summary builder). Wire-format details live in
:mod:`asta.utils.a2a_stream`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from asta.utils.a2a_stream import (
    A2AStreamError,
    artifact_data_of,
    step_progress_of,
    stream_a2a_message,
    terminal_status_of,
)
from asta.utils.config import get_api_config, get_config_path
from asta.utils.thread_state import (
    ThreadState,
    load_thread_state,
    make_turn_entry,
    save_thread_state,
    turn_filename,
)

COMPLETED_STATE = "TASK_STATE_COMPLETED"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class A2ASkillSpec:
    """``config_key`` is the ``apis.<key>`` block in ``asta.conf`` (reads
    ``a2a_url`` then ``base_url``); ``env_var`` is the per-skill override
    the user can set instead of ``--server``."""

    config_key: str
    env_var: str


@dataclass(frozen=True, slots=True)
class TurnResult:
    artifact: dict[str, Any]
    thread_id: str | None
    narrative: str | None


# (artifact_dict, thread_id, narrative) → result with ``.model_dump`` or a plain dict.
ArtifactToResult = Callable[[dict[str, Any], str | None, str | None], Any]

# (result_obj, narrative) → per-turn ``summary`` blob recorded under ``DIR/index.json``.
BuildSummary = Callable[[Any, str | None], dict[str, Any]]


def standard_a2a_options(f: Callable) -> Callable:
    """Click decorator: ``-o``, ``--thread-dir``, ``--timeout``, ``--server``, ``--api-key``."""
    options = [
        click.option(
            "-o",
            "--output",
            type=click.Path(),
            required=True,
            help="Output file path for the results (required)",
        ),
        click.option(
            "--thread-dir",
            type=click.Path(file_okay=False),
            default=None,
            help=(
                "Directory to persist thread state. When set, -o is treated as "
                "a basename, the actual file becomes DIR/<stem>.NNN.<ext> "
                "(NNN = turn index), and DIR/index.json records ordered turn "
                "metadata + thread_id for auto-resume on the next call. Omit "
                "for a one-shot turn that doesn't continue any prior conversation."
            ),
        ),
        click.option(
            "--timeout",
            type=int,
            default=600,
            help="HTTP timeout per request in seconds (default 600).",
        ),
        click.option(
            "--server",
            default=None,
            help=(
                "A2A agent base URL (default: skill's a2a_url from asta.conf, "
                "or the skill-specific env var)."
            ),
        ),
        click.option(
            "--api-key",
            default=None,
            help=(
                "Bearer token. Optional: required only when the server enforces "
                "auth (gateway path). Default: `asta auth` token, or "
                "ASTA_A2A_API_KEY env."
            ),
        ),
    ]
    for opt in reversed(options):
        f = opt(f)
    return f


def run_a2a_session(
    spec: A2ASkillSpec,
    *,
    output: str,
    thread_dir: str | None,
    timeout: int,
    server: str | None,
    api_key: str | None,
    message_data: dict[str, Any],
    artifact_to_result: ArtifactToResult,
    build_summary: BuildSummary | None = None,
) -> None:
    """Resolve server/auth, prep ``--thread-dir``, stream the turn, write output, update index.

    Conversation continuation is via ``--thread-dir`` only: ``DIR/index.json``
    carries the prior turn's ``thread_id`` and the runner auto-resumes off it.
    Without ``--thread-dir`` every invocation is a one-shot turn.

    Raises :class:`click.ClickException` for any user-facing failure.
    """
    try:
        # 1. Resolve session inputs (thread-dir state, server URL, auth).
        thread_dir_path, state, resolved_thread_id, turn_idx = _prepare_thread_dir(
            thread_dir=thread_dir, output=output
        )
        resolved_server = _resolve_server(server, spec=spec)
        resolved_key = _resolve_api_key(api_key)

        # 2. Stream the turn.
        stream_result = asyncio.run(
            _run_streaming_turn(
                message_data=message_data,
                thread_id=resolved_thread_id,
                server=resolved_server,
                api_key=resolved_key,
                timeout=timeout,
            )
        )

        # 3. Translate the wire artifact into the skill's result type.
        result_obj = artifact_to_result(
            stream_result.artifact,
            stream_result.thread_id,
            stream_result.narrative,
        )

        # 4. Persist outputs: write the result file and, in thread-dir mode,
        #    append a turn entry to DIR/index.json.
        output_path = _persist_turn(
            output=output,
            thread_dir_path=thread_dir_path,
            state=state,
            turn=turn_idx,
            result_obj=result_obj,
            stream_result=stream_result,
            build_summary=build_summary,
        )

        # 5. Echo completion.
        thread_suffix = (
            f" (thread_id={stream_result.thread_id})"
            if stream_result.thread_id
            else ""
        )
        click.echo(f"Results saved to: {output_path}{thread_suffix}", err=True)

    except click.ClickException:
        # Includes UsageError (subclass), so it must be matched before Exception.
        raise
    except Exception as e:
        raise click.ClickException(str(e)) from e


# ---------------------------------------------------------------------------
# Private helpers (in call order from ``run_a2a_session``)
# ---------------------------------------------------------------------------


def _prepare_thread_dir(
    *,
    thread_dir: str | None,
    output: str,
) -> tuple[Path | None, ThreadState | None, str | None, int]:
    if thread_dir is None:
        return None, None, None, 1
    if Path(output).name != output:
        raise click.UsageError(
            "When --thread-dir is set, -o must be a basename (no path "
            f"separators). Got: {output!r}"
        )
    thread_dir_path = Path(thread_dir)
    state = load_thread_state(thread_dir_path)
    resolved_thread_id = state.thread_id if state else None
    turn_idx = state.next_turn_index() if state else 1
    return thread_dir_path, state, resolved_thread_id, turn_idx


def _resolve_server(server: str | None, *, spec: A2ASkillSpec) -> str:
    if server:
        return server.rstrip("/")
    if env := os.environ.get(spec.env_var):
        return env.rstrip("/")
    try:
        config = get_api_config(spec.config_key)
    except (KeyError, FileNotFoundError):
        config = {}
    if a2a_url := config.get("a2a_url"):
        return str(a2a_url).rstrip("/")
    if base_url := config.get("base_url"):
        return str(base_url).rstrip("/")
    raise click.ClickException(
        f"No A2A server configured for skill '{spec.config_key}'. Pass --server, "
        f"set {spec.env_var}, or add apis.{spec.config_key}.a2a_url to "
        f"{get_config_path()}."
    )


def _resolve_api_key(api_key: str | None) -> str | None:
    # Best-effort: gateway-side auth means a missing token is fine for unauth'd backends.
    if api_key:
        return api_key
    if env := (os.environ.get("ASTA_A2A_API_KEY") or os.environ.get("API_KEY")):
        return env
    try:
        from asta.utils.auth_helper import get_access_token

        return get_access_token()
    except Exception:
        return None


async def _run_streaming_turn(
    *,
    message_data: dict[str, Any],
    thread_id: str | None,
    server: str,
    api_key: str | None,
    timeout: int,
) -> TurnResult:
    """Drives a single turn; prints step-progress to stderr; enforces the
    ``COMPLETED`` + artifact-present terminal policy (else raises)."""
    resolved_thread_id: str | None = thread_id
    artifact_dict: dict[str, Any] | None = None
    narrative: str | None = None
    terminal_state: str | None = None
    thread_id_announced = False

    def _announce(rt: str | None) -> None:
        nonlocal resolved_thread_id, thread_id_announced
        if rt and not thread_id_announced:
            resolved_thread_id = resolved_thread_id or rt
            print(f"thread_id: {resolved_thread_id}", file=sys.stderr, flush=True)
            thread_id_announced = True

    try:
        async for event in stream_a2a_message(
            server=server,
            message_data=message_data,
            context_id=thread_id,
            api_key=api_key,
            timeout=timeout,
        ):
            _announce(event.context_id)
            if event.kind == "status_update":
                if (terminal := terminal_status_of(event)) is not None:
                    terminal_state = terminal.state
                    narrative = terminal.text or narrative
                elif (progress := step_progress_of(event)) is not None:
                    desc = (
                        progress.get("short_desc")
                        or progress.get("long_desc")
                        or ""
                    )
                    marker = "  ✗" if progress.get("run_state") == "failed" else "  •"
                    print(f"{marker} {desc}", file=sys.stderr, flush=True)
            elif event.kind == "artifact_update":
                if (payload := artifact_data_of(event)) is not None:
                    artifact_dict = payload
    except A2AStreamError as e:
        raise click.ClickException(str(e)) from e

    if terminal_state is None:
        raise click.ClickException(
            "Stream ended before a terminal status was received."
        )
    if terminal_state != COMPLETED_STATE:
        raise click.ClickException(
            f"Search ended in state '{terminal_state}': {narrative or ''}"
        )
    if artifact_dict is None:
        raise click.ClickException("Search completed but no artifact was returned.")

    return TurnResult(
        artifact=artifact_dict,
        thread_id=resolved_thread_id,
        narrative=narrative,
    )


def _persist_turn(
    *,
    output: str,
    thread_dir_path: Path | None,
    state: ThreadState | None,
    turn: int,
    result_obj: Any,
    stream_result: TurnResult,
    build_summary: BuildSummary | None,
) -> Path:
    """Write the result file and (in thread-dir mode) append to ``DIR/index.json``.
    Returns the on-disk path the file was written to."""
    output_path, artifact_basename = _resolve_output_path(output, thread_dir_path, turn)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(_serialize(result_obj), f, indent=2)
    if thread_dir_path is not None and artifact_basename is not None:
        _record_turn_in_index(
            thread_dir=thread_dir_path,
            state=state,
            turn=turn,
            file=artifact_basename,
            result_obj=result_obj,
            stream_result=stream_result,
            build_summary=build_summary,
        )
    return output_path


def _resolve_output_path(
    output: str, thread_dir_path: Path | None, turn: int
) -> tuple[Path, str | None]:
    """``(path, basename)``. ``basename`` is set only in thread-dir mode (used as
    the entry's ``file`` field in ``index.json``); ``None`` for one-shot turns."""
    if thread_dir_path is None:
        return Path(output), None
    basename = turn_filename(Path(output).name, turn)
    return thread_dir_path / basename, basename


def _record_turn_in_index(
    *,
    thread_dir: Path,
    state: ThreadState | None,
    turn: int,
    file: str,
    result_obj: Any,
    stream_result: TurnResult,
    build_summary: BuildSummary | None,
) -> None:
    summary = (
        build_summary(result_obj, stream_result.narrative) if build_summary else {}
    )
    if state is None:
        state = ThreadState.fresh(thread_id=stream_result.thread_id)
    elif state.thread_id is None and stream_result.thread_id:
        state.thread_id = stream_result.thread_id
    state.turns.append(make_turn_entry(turn=turn, file=file, summary=summary))
    save_thread_state(thread_dir, state)


def _serialize(result_obj: Any) -> Any:
    # Pydantic ``BaseModel`` instances expose ``model_dump``; everything else
    # falls through to ``json.dump`` as-is.
    dump = getattr(result_obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=False)
    return result_obj
