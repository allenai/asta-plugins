"""Streaming client for A2A v1.0 ``SendStreamingMessage`` JSON-RPC over SSE.

Wire-format only. Higher-level concerns (terminal-state policy,
step-progress display, output writing, ``--thread-dir`` persistence) live in
:mod:`asta.utils.a2a_interactive`. Use this module directly only when you
need the raw event stream without the session orchestration.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple
from uuid import uuid4

import httpx

A2A_VERSION = "1.0"
DEFAULT_RPC_PATH = "/api/3/a2a"

# A2A v1.0 task lifecycle states that are terminal (no further events follow).
TERMINAL_STATES: frozenset[str] = frozenset(
    {
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_REJECTED",
    }
)

EventKind = Literal["task", "status_update", "artifact_update"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class A2AEvent:
    kind: EventKind
    context_id: str | None
    raw: dict[str, Any]


class TerminalStatus(NamedTuple):
    state: str
    text: str


class A2AStreamError(Exception):
    pass


async def stream_a2a_message(
    *,
    server: str,
    message_data: dict[str, Any],
    context_id: str | None = None,
    api_key: str | None = None,
    timeout: int = 600,
    rpc_path: str = DEFAULT_RPC_PATH,
) -> AsyncIterator[A2AEvent]:
    """Send ``SendStreamingMessage`` and yield parsed events.

    ``context_id`` continues a prior conversation when set on the message
    envelope. ``api_key`` is omitted from headers when ``None`` (gateway-side
    auth or unauth'd local backends).

    Raises :class:`A2AStreamError` on HTTP non-200 or JSON-RPC error response.
    """
    headers = {
        "A2A-Version": A2A_VERSION,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = _build_rpc_body(message_data, context_id)
    url = f"{server.rstrip('/')}{rpc_path}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as http:
        async with http.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                payload = (await response.aread()).decode(errors="replace")
                raise A2AStreamError(
                    f"A2A request failed (HTTP {response.status_code}): {payload}"
                )
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                envelope = json.loads(line.removeprefix("data:").strip())
                if "error" in envelope:
                    err = envelope["error"]
                    if isinstance(err, dict):
                        raise A2AStreamError(
                            f"A2A error {err.get('code')}: {err.get('message')}"
                        )
                    raise A2AStreamError(f"A2A error: {err}")
                event = _parse_result(envelope.get("result") or {})
                if event is not None:
                    yield event


# Extractors for callers post-processing yielded events.


def step_progress_of(event: A2AEvent) -> dict[str, Any] | None:
    if event.kind != "status_update":
        return None
    msg = (event.raw.get("status") or {}).get("message") or {}
    for part in msg.get("parts", []):
        data = part.get("data")
        if isinstance(data, dict) and data.get("kind") == "step-progress":
            return data
    return None


def terminal_status_of(event: A2AEvent) -> TerminalStatus | None:
    if event.kind != "status_update":
        return None
    status = event.raw.get("status") or {}
    state = status.get("state")
    if not isinstance(state, str) or state not in TERMINAL_STATES:
        return None
    msg = status.get("message") or {}
    text = next(
        (
            p["text"]
            for p in msg.get("parts", [])
            if isinstance(p.get("text"), str) and p["text"]
        ),
        "",
    )
    return TerminalStatus(state=state, text=text)


def artifact_data_of(event: A2AEvent) -> dict[str, Any] | None:
    if event.kind != "artifact_update":
        return None
    artifact = event.raw.get("artifact") or {}
    for part in artifact.get("parts", []):
        data = part.get("data")
        if isinstance(data, dict):
            return data
    return None


# ---------------------------------------------------------------------------
# Private helpers (in call order from ``stream_a2a_message``)
# ---------------------------------------------------------------------------


def _build_rpc_body(
    message_data: dict[str, Any], context_id: str | None
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "messageId": uuid4().hex,
        "role": "ROLE_USER",
        "parts": [{"data": {"data": message_data}}],
    }
    if context_id:
        # Standard A2A continuation mechanism: the prior Task's context_id is
        # echoed back on the next request envelope to link the conversation.
        message["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "id": "stream",
        "method": "SendStreamingMessage",
        "params": {"message": message},
    }


def _parse_result(result: dict[str, Any]) -> A2AEvent | None:
    # Returns None for unrecognised event kinds → forward-compat with new server events.
    if "task" in result:
        task = result["task"]
        return A2AEvent(kind="task", context_id=task.get("contextId"), raw=task)
    if "statusUpdate" in result:
        upd = result["statusUpdate"]
        return A2AEvent(kind="status_update", context_id=upd.get("contextId"), raw=upd)
    if "artifactUpdate" in result:
        upd = result["artifactUpdate"]
        return A2AEvent(kind="artifact_update", context_id=upd.get("contextId"), raw=upd)
    return None
