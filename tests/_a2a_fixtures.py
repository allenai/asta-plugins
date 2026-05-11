"""Test helpers for stubbing the A2A streaming endpoint.

Use :class:`FakeA2AServer` as a context manager: it replaces ``httpx.AsyncClient``
with a fake that returns canned SSE events and captures every outgoing request
body. The ``happy_events`` / ``failed_events`` helpers below produce the most
common server-side scenarios; pass your own list for finer control.

    with FakeA2AServer(events=happy_events()) as server:
        runner.invoke(cli, [...])
    assert server.requests[0]["params"]["message"]["contextId"] == "thrd:abc"

This module is private (leading underscore) so pytest's collection skips it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

DEFAULT_THREAD_ID = "thrd:abc"
DEFAULT_TASK_ID = "task-1"


class FakeA2AServer:
    """Stand-in for the mabool A2A endpoint, mounted over ``httpx.AsyncClient``.

    Args:
        events: SSE event envelopes to yield (as wire dicts; see
            :func:`initial_task_event` etc.). Ignored when ``status != 200``.
        status: HTTP status code for the streaming response. Use a non-200
            value to simulate transport-level errors.
        body: Raw response body for non-200 responses. Surfaced inside the
            ``A2AStreamError`` raised by the client.

    After ``__exit__`` the captured request bodies are available on
    ``self.requests`` (one entry per ``.stream()`` call made within the
    context manager).
    """

    def __init__(
        self,
        *,
        events: list[dict[str, Any]] | None = None,
        status: int = 200,
        body: bytes = b"",
    ) -> None:
        self._events = events or []
        self._status = status
        self._body = body
        self.requests: list[dict[str, Any]] = []
        self._patcher: Any = None

    def __enter__(self) -> FakeA2AServer:
        response = _FakeStreamResponse(
            lines=[_sse_line(e) for e in self._events],
            status_code=self._status,
            body=self._body,
        )
        client = MagicMock()

        def stream(*_args: Any, **kwargs: Any) -> _FakeStreamResponse:
            self.requests.append(kwargs.get("json"))
            return response

        client.stream = MagicMock(side_effect=stream)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        self._patcher = patch(
            "asta.utils.a2a_stream.httpx.AsyncClient", return_value=client
        )
        self._patcher.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._patcher is not None:
            self._patcher.stop()


# --- Pre-built event sequences ------------------------------------------------


def happy_events(
    narrative: str = "Found 1 paper.",
    artifact_data: dict[str, Any] | None = None,
    thread_id: str = DEFAULT_THREAD_ID,
) -> list[dict[str, Any]]:
    """Initial-submitted → working step → artifact → completed-terminal."""
    return [
        initial_task_event(thread_id=thread_id),
        working_step_event("Searching"),
        artifact_update_event(artifact_data or _MIN_ARTIFACT, thread_id=thread_id),
        terminal_event("TASK_STATE_COMPLETED", narrative, thread_id=thread_id),
    ]


def failed_events(
    narrative: str = "Bad things",
    thread_id: str = DEFAULT_THREAD_ID,
) -> list[dict[str, Any]]:
    """Initial-submitted → failed-terminal."""
    return [
        initial_task_event(thread_id=thread_id),
        terminal_event("TASK_STATE_FAILED", narrative, thread_id=thread_id),
    ]


# --- Individual event builders ------------------------------------------------


def initial_task_event(thread_id: str = DEFAULT_THREAD_ID) -> dict[str, Any]:
    return _envelope(
        "task",
        {
            "id": DEFAULT_TASK_ID,
            "contextId": thread_id,
            "status": {"state": "TASK_STATE_SUBMITTED"},
        },
    )


def working_step_event(
    short_desc: str, thread_id: str = DEFAULT_THREAD_ID
) -> dict[str, Any]:
    return _envelope(
        "statusUpdate",
        {
            "taskId": DEFAULT_TASK_ID,
            "contextId": thread_id,
            "status": {
                "state": "TASK_STATE_WORKING",
                "message": {
                    "parts": [
                        {"text": short_desc},
                        {
                            "data": {
                                "kind": "step-progress",
                                "step_id": "s-1",
                                "short_desc": short_desc,
                                "run_state": "running",
                            }
                        },
                    ]
                },
            },
        },
    )


def artifact_update_event(
    artifact_data: dict[str, Any], thread_id: str = DEFAULT_THREAD_ID
) -> dict[str, Any]:
    return _envelope(
        "artifactUpdate",
        {
            "taskId": DEFAULT_TASK_ID,
            "contextId": thread_id,
            "artifact": {
                "artifactId": DEFAULT_TASK_ID,
                "name": "Result",
                "parts": [{"data": artifact_data}],
            },
        },
    )


def terminal_event(
    state: str, text: str, thread_id: str = DEFAULT_THREAD_ID
) -> dict[str, Any]:
    return _envelope(
        "statusUpdate",
        {
            "taskId": DEFAULT_TASK_ID,
            "contextId": thread_id,
            "status": {
                "state": state,
                "message": {"parts": [{"text": text}]},
            },
        },
    )


# --- Internals ---------------------------------------------------------------


_MIN_ARTIFACT: dict[str, Any] = {"schemaVersion": "1", "entities": {}}


def _envelope(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"result": {kind: payload}, "id": "stream", "jsonrpc": "2.0"}


def _sse_line(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}"


class _FakeStreamResponse:
    def __init__(
        self, lines: list[str], status_code: int = 200, body: bytes = b""
    ) -> None:
        self._lines = lines
        self.status_code = status_code
        self._body = body

    async def __aenter__(self) -> _FakeStreamResponse:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body
