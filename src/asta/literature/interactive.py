"""Interactive (multi-turn) literature search via the mabool A2A endpoint.

Mirrors ``asta literature find``'s output shape (``LiteratureSearchResult``) but
maintains conversational state across turns via ``thread_id``. Step-progress
events stream to stderr while the search runs; the final artifact is written
to ``-o``.

Talks to the A2A endpoint over JSON-RPC 2.0 with method
``SendStreamingMessage`` (per ``api/docs/guides/A2A.md``). The SSE response is
parsed line-by-line; each event's ``result`` envelope is one of ``task``,
``statusUpdate``, or ``artifactUpdate``.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import click
import httpx

from asta.literature.a2a_artifact import parse_artifact
from asta.literature.thread_state import (
    ThreadState,
    load_thread_state,
    make_turn_entry,
    save_thread_state,
    turn_filename,
)
from asta.utils.config import get_api_config, get_config_path

RPC_PATH = "/api/3/a2a"

TERMINAL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}


# ---------------------------------------------------------------------------
# Public CLI entry point
# ---------------------------------------------------------------------------


@click.command()
@click.argument("query")
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    required=True,
    help="Output file path for the results (required)",
)
@click.option(
    "--thread-id",
    default=None,
    help="Continue an existing conversation. Omit to start a new one.",
)
@click.option(
    "--thread-dir",
    type=click.Path(file_okay=False),
    default=None,
    help=(
        "Directory to persist thread state. When set, -o is treated as a "
        "basename, the actual file becomes DIR/<stem>.NNN.<ext> (NNN = turn "
        "index), and DIR/index.json records ordered turn metadata + thread_id "
        "for auto-resume on the next call."
    ),
)
@click.option(
    "--mode",
    type=click.Choice(["infer", "fast", "diligent"]),
    default="infer",
    help="Search strategy: infer (auto-detect), fast (quick), or diligent (comprehensive)",
)
@click.option(
    "--timeout",
    type=int,
    default=600,
    help="HTTP timeout per request in seconds (default 600).",
)
@click.option(
    "--server",
    default=None,
    help=(
        "A2A agent base URL (default: apis.paper_finder.a2a_url from asta.conf, "
        "or ASTA_PAPER_FINDER_A2A_URL env)."
    ),
)
@click.option(
    "--api-key",
    default=None,
    help=(
        "Bearer token. Optional: required only when the server enforces auth "
        "(gateway path). Default: `asta auth` token, or ASTA_A2A_API_KEY env."
    ),
)
def interactive(
    query: str,
    output: str,
    thread_id: str | None,
    thread_dir: str | None,
    mode: str,
    timeout: int,
    server: str | None,
    api_key: str | None,
):
    """Conduct a stateful, multi-turn literature search via the Asta Paper Finder A2A endpoint.

    Pass --thread-id <id> to continue a prior conversation; omit it to start a
    new one. Or pass --thread-dir DIR to persist all turns of a session — the
    CLI then auto-resumes thread_id from DIR/index.json and writes per-turn
    artifacts as DIR/<-o stem>.NNN.<ext> so the conversation can be replayed.

    Output schema mirrors `asta literature find` (LiteratureSearchResult), with
    additional `thread_id` and `narrative` fields.

    Examples:

        # Start a new conversation
        asta literature interactive "transformer architecture survey" -o /tmp/r1.json

        # Continue the same conversation explicitly
        asta literature interactive "narrow to 2023+ surveys" --thread-id <id> -o /tmp/r2.json

        # Persisted multi-turn session (recommended for exploratory work)
        asta literature interactive "transformer architecture survey" \\
          --thread-dir .asta/literature/threads/transformers -o transformer-survey.json
        asta literature interactive "narrow to 2023+ surveys" \\
          --thread-dir .asta/literature/threads/transformers -o narrow-2023.json
        # → DIR/transformer-survey.001.json, DIR/narrow-2023.002.json, DIR/index.json

        # Local mabool dev server (no auth — the gateway handles it in prod)
        asta literature interactive "deep learning" \\
          --server http://localhost:8000 -o /tmp/r.json
    """
    try:
        thread_dir_path, state, resolved_thread_id, turn_idx = _prepare_thread_dir(
            thread_dir=thread_dir, output=output, explicit_thread_id=thread_id
        )

        resolved_server = _resolve_server(server)
        resolved_key = _resolve_api_key(api_key)
        result = asyncio.run(
            _run_interactive(
                query=query,
                mode=mode,
                thread_id=resolved_thread_id,
                server=resolved_server,
                api_key=resolved_key,
                timeout=timeout,
            )
        )

        literature_result = parse_artifact(
            result["artifact"],
            query=query,
            thread_id=result.get("thread_id"),
            narrative=result.get("narrative"),
        )

        if thread_dir_path is not None:
            artifact_basename = turn_filename(Path(output).name, turn_idx)
            output_path = thread_dir_path / artifact_basename
        else:
            artifact_basename = None
            output_path = Path(output)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(
                literature_result.model_dump(mode="json", exclude_none=False),
                f,
                indent=2,
            )

        if thread_dir_path is not None:
            assert artifact_basename is not None
            _record_turn_in_index(
                thread_dir=thread_dir_path,
                state=state,
                turn=turn_idx,
                query=query,
                mode=mode,
                narrative=result.get("narrative"),
                paper_count=len(literature_result.results),
                file=artifact_basename,
                thread_id=result.get("thread_id"),
            )

        thread_suffix = (
            f" (thread_id={result['thread_id']})" if result.get("thread_id") else ""
        )
        click.echo(f"Results saved to: {output_path}{thread_suffix}", err=True)

    except click.ClickException:
        # Includes UsageError (subclass), so it must be matched before Exception.
        raise
    except Exception as e:
        raise click.ClickException(str(e))


# ---------------------------------------------------------------------------
# Thread-dir helpers (called by `interactive`)
# ---------------------------------------------------------------------------


def _prepare_thread_dir(
    *,
    thread_dir: str | None,
    output: str,
    explicit_thread_id: str | None,
) -> tuple[Path | None, ThreadState | None, str | None, int]:
    """Validate inputs and load any existing thread state.

    Returns ``(thread_dir_path, state, resolved_thread_id, turn_index)``. When
    ``thread_dir`` is None, returns ``(None, None, explicit_thread_id, 1)``.
    """
    if thread_dir is None:
        return None, None, explicit_thread_id, 1

    if Path(output).name != output:
        raise click.UsageError(
            "When --thread-dir is set, -o must be a basename (no path "
            f"separators). Got: {output!r}"
        )

    thread_dir_path = Path(thread_dir)
    state = load_thread_state(thread_dir_path)
    resolved_thread_id = explicit_thread_id

    if state and state.thread_id:
        if explicit_thread_id and explicit_thread_id != state.thread_id:
            raise click.UsageError(
                f"--thread-id={explicit_thread_id!r} disagrees with index at "
                f"{thread_dir_path}/index.json (thread_id={state.thread_id!r}). "
                "Drop --thread-id, or point at a fresh --thread-dir."
            )
        resolved_thread_id = state.thread_id

    turn_idx = state.next_turn_index() if state else 1
    return thread_dir_path, state, resolved_thread_id, turn_idx


def _record_turn_in_index(
    *,
    thread_dir: Path,
    state: ThreadState | None,
    turn: int,
    query: str,
    mode: str,
    narrative: str | None,
    paper_count: int,
    file: str,
    thread_id: str | None,
) -> None:
    """Append a turn entry to the thread's index.json (creating it if absent)."""
    if state is None:
        state = ThreadState.fresh(thread_id=thread_id)
    elif state.thread_id is None and thread_id:
        state.thread_id = thread_id
    state.turns.append(
        make_turn_entry(
            turn=turn,
            query=query,
            mode=mode,
            narrative=narrative,
            paper_count=paper_count,
            file=file,
        )
    )
    save_thread_state(thread_dir, state)


# ---------------------------------------------------------------------------
# Server / auth resolution (called by `interactive`)
# ---------------------------------------------------------------------------


def _resolve_server(server: str | None) -> str:
    if server:
        return server.rstrip("/")
    if env := os.environ.get("ASTA_PAPER_FINDER_A2A_URL"):
        return env.rstrip("/")
    try:
        config = get_api_config("paper_finder")
    except (KeyError, FileNotFoundError):
        config = {}
    if a2a_url := config.get("a2a_url"):
        return str(a2a_url).rstrip("/")
    if base_url := config.get("base_url"):
        return str(base_url).rstrip("/")
    raise click.ClickException(
        f"No paper-finder A2A server configured. Pass --server, set "
        f"ASTA_PAPER_FINDER_A2A_URL, or add apis.paper_finder.a2a_url to "
        f"{get_config_path()}."
    )


def _resolve_api_key(api_key: str | None) -> str | None:
    """Best-effort bearer-token lookup. Returns None when nothing is configured.

    The mabool A2A endpoint itself is unauthenticated; auth is enforced by the
    asta gateway. So a missing token is fine when pointing directly at a local
    or otherwise-unauth'd backend, but is needed when going through the gateway.
    """
    if api_key:
        return api_key
    if env := (os.environ.get("ASTA_A2A_API_KEY") or os.environ.get("API_KEY")):
        return env
    try:
        from asta.utils.auth_helper import get_access_token

        return get_access_token()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# A2A streaming client (called by `interactive`)
# ---------------------------------------------------------------------------


async def _run_interactive(
    *,
    query: str,
    mode: str,
    thread_id: str | None,
    server: str,
    api_key: str | None,
    timeout: int,
) -> dict[str, Any]:
    headers = {
        "A2A-Version": "1.0",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = f"{server}{RPC_PATH}"
    body = _build_rpc_body(query, mode, thread_id)

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

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as http:
        async with http.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                payload = (await response.aread()).decode(errors="replace")
                raise click.ClickException(
                    f"A2A request failed (HTTP {response.status_code}): {payload}"
                )
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                envelope = json.loads(line.removeprefix("data:").strip())
                if "error" in envelope:
                    err = envelope["error"]
                    if isinstance(err, dict):
                        raise click.ClickException(
                            f"A2A error {err.get('code')}: {err.get('message')}"
                        )
                    raise click.ClickException(f"A2A error: {err}")
                result = envelope.get("result") or {}
                if "task" in result:
                    task = result["task"]
                    metadata = task.get("metadata") or {}
                    _announce(metadata.get("thread_id"))
                elif "statusUpdate" in result:
                    upd = result["statusUpdate"]
                    metadata = upd.get("metadata") or {}
                    _announce(metadata.get("thread_id"))
                    state = (upd.get("status") or {}).get("state")
                    msg = (upd.get("status") or {}).get("message") or {}
                    if state == "TASK_STATE_WORKING":
                        payload = _step_payload(msg)
                        if payload:
                            desc = (
                                payload.get("short_desc")
                                or payload.get("long_desc")
                                or ""
                            )
                            run_state = payload.get("run_state", "")
                            marker = "  ✗" if run_state == "failed" else "  •"
                            print(f"{marker} {desc}", file=sys.stderr, flush=True)
                    elif state in TERMINAL_STATES:
                        terminal_state = state
                        narrative = _terminal_text(msg) or narrative
                elif "artifactUpdate" in result:
                    upd = result["artifactUpdate"]
                    metadata = upd.get("metadata") or {}
                    _announce(metadata.get("thread_id"))
                    payload = _artifact_payload(upd.get("artifact") or {})
                    if payload is not None:
                        artifact_dict = payload

    if terminal_state is None:
        raise click.ClickException(
            "Stream ended before a terminal status was received."
        )
    if terminal_state != "TASK_STATE_COMPLETED":
        raise click.ClickException(
            f"Search ended in state '{terminal_state}': {narrative or ''}"
        )
    if artifact_dict is None:
        raise click.ClickException("Search completed but no artifact was returned.")

    return {
        "artifact": artifact_dict,
        "thread_id": resolved_thread_id,
        "narrative": narrative,
    }


# ---------------------------------------------------------------------------
# JSON-RPC envelope + SSE event parsing helpers (called by `_run_interactive`)
# ---------------------------------------------------------------------------


def _build_rpc_body(query: str, mode: str, thread_id: str | None) -> dict[str, Any]:
    inner: dict[str, Any] = {"query": query, "operation_mode": mode}
    if thread_id:
        inner["thread_id"] = thread_id
    message: dict[str, Any] = {
        "messageId": uuid4().hex,
        "role": "ROLE_USER",
        "parts": [{"data": {"data": inner}}],
    }
    if thread_id:
        # A2A's ``contextId`` groups messages in a conversation — same notion
        # as mabool's ``thread_id``, so we send the same value on both routes.
        message["contextId"] = thread_id
    return {
        "jsonrpc": "2.0",
        "id": "stream",
        "method": "SendStreamingMessage",
        "params": {"message": message},
    }


def _step_payload(message: dict[str, Any]) -> dict[str, Any] | None:
    for part in message.get("parts", []):
        data = part.get("data")
        if isinstance(data, dict) and data.get("kind") == "step-progress":
            return data
    return None


def _terminal_text(message: dict[str, Any]) -> str:
    for part in message.get("parts", []):
        text = part.get("text")
        if isinstance(text, str) and text:
            return text
    return ""


def _artifact_payload(artifact: dict[str, Any]) -> dict[str, Any] | None:
    for part in artifact.get("parts", []):
        data = part.get("data")
        if isinstance(data, dict):
            return data
    return None
