"""Tests for ``asta.utils.a2a_stream``.

The streaming flow itself (httpx → SSE → parsed events) is exercised
end-to-end by the e2e tests in ``test_interactive.py``. The tests here
target the wire-format details that e2e doesn't easily probe: the
JSON-RPC body shape (especially ``contextId`` placement), and the
extractor functions' behaviour on non-matching event kinds.
"""

import pytest

from asta.utils.a2a_stream import (
    A2AEvent,
    _build_rpc_body,
    artifact_data_of,
    step_progress_of,
    terminal_status_of,
)


@pytest.mark.parametrize(
    "context_id,expect_context_id",
    [(None, False), ("thrd:xyz", True)],
)
def test_build_rpc_body_contextid_placement(context_id, expect_context_id):
    """``contextId`` rides on the message envelope only — never on the data part."""
    body = _build_rpc_body({"query": "hi", "operation_mode": "fast"}, context_id)
    message = body["params"]["message"]
    assert body["method"] == "SendStreamingMessage"
    assert message["role"] == "ROLE_USER"
    assert message["parts"][0]["data"]["data"] == {
        "query": "hi",
        "operation_mode": "fast",
    }
    if expect_context_id:
        assert message["contextId"] == context_id
    else:
        assert "contextId" not in message


def test_extractors_match_only_their_event_kind():
    """Each extractor returns its payload for the right kind, ``None`` otherwise.
    The happy-path-of-each is exercised by e2e; this locks down the negative
    cases and the kind-vs-shape mismatch handling that e2e doesn't reach."""
    task = A2AEvent(
        kind="task",
        context_id="thrd:abc",
        raw={"id": "t-1", "contextId": "thrd:abc"},
    )
    working = A2AEvent(
        kind="status_update",
        context_id="thrd:abc",
        raw={
            "status": {
                "state": "TASK_STATE_WORKING",
                "message": {
                    "parts": [
                        {"text": "Working"},
                        {
                            "data": {
                                "kind": "step-progress",
                                "step_id": "s-1",
                                "short_desc": "Working",
                                "run_state": "running",
                            }
                        },
                    ]
                },
            }
        },
    )
    completed = A2AEvent(
        kind="status_update",
        context_id="thrd:abc",
        raw={
            "status": {
                "state": "TASK_STATE_COMPLETED",
                "message": {"parts": [{"text": "All done"}]},
            }
        },
    )
    artifact = A2AEvent(
        kind="artifact_update",
        context_id="thrd:abc",
        raw={
            "artifact": {
                "parts": [{"data": {"schemaVersion": "1", "entities": {}}}],
            }
        },
    )

    # step_progress_of: only matches working status with a step-progress data part.
    assert step_progress_of(working) is not None
    assert step_progress_of(working)["short_desc"] == "Working"
    assert step_progress_of(task) is None
    assert step_progress_of(completed) is None  # status_update but no step-progress
    assert step_progress_of(artifact) is None

    # terminal_status_of: only matches status_update with a terminal state.
    terminal = terminal_status_of(completed)
    assert terminal is not None and terminal.state == "TASK_STATE_COMPLETED"
    assert terminal.text == "All done"
    assert terminal_status_of(working) is None
    assert terminal_status_of(task) is None
    assert terminal_status_of(artifact) is None

    # artifact_data_of: only matches artifact_update events.
    assert artifact_data_of(artifact) == {"schemaVersion": "1", "entities": {}}
    assert artifact_data_of(task) is None
    assert artifact_data_of(working) is None
