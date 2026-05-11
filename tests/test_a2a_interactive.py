"""Tests for ``asta.utils.a2a_interactive``.

The e2e tests run :func:`run_a2a_session` against a :class:`FakeA2AServer`
(mocking only ``httpx.AsyncClient``), so the full streaming + thread-dir
persistence + output stack runs for real.

Resolver precedence tests live at the end of the file: env/config interactions
are awkward to permute via e2e, so they're covered as focused unit tests.
"""

import json
from unittest.mock import patch

import click
import pytest

from asta.utils.a2a_interactive import (
    A2ASkillSpec,
    _resolve_api_key,
    _resolve_server,
    run_a2a_session,
)
from tests._a2a_fixtures import (
    DEFAULT_THREAD_ID,
    FakeA2AServer,
    failed_events,
    happy_events,
)

SPEC = A2ASkillSpec(config_key="test_skill", env_var="ASTA_TEST_SKILL_A2A_URL")


@pytest.fixture(autouse=True)
def _stub_resolver_env(monkeypatch):
    """Resolve to a dummy URL without auth, so ``run_a2a_session`` reaches the
    httpx layer (which the FakeA2AServer has patched)."""
    monkeypatch.setenv(SPEC.env_var, "http://test-server")
    monkeypatch.delenv("ASTA_A2A_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)


# --- End-to-end -------------------------------------------------------------


def _identity_artifact_to_result(artifact, thread_id, narrative):
    """Stub callback — passes the wire artifact + metadata through as a dict."""
    return {
        "thread_id": thread_id,
        "narrative": narrative,
        "schema": artifact.get("schemaVersion"),
    }


def test_e2e_single_turn_writes_result(tmp_path):
    """Click-less e2e: stream → artifact → ``artifact_to_result`` → file."""
    out = tmp_path / "result.json"
    with FakeA2AServer(events=happy_events()):
        run_a2a_session(
            SPEC,
            output=str(out),
            thread_dir=None,
            timeout=30,
            server=None,
            api_key=None,
            message_data={"q": "hello"},
            artifact_to_result=_identity_artifact_to_result,
        )

    data = json.loads(out.read_text())
    assert data == {
        "thread_id": DEFAULT_THREAD_ID,
        "narrative": "Found 1 paper.",
        "schema": "1",
    }


def test_e2e_multi_turn_thread_dir_resumes_via_context_id(tmp_path):
    """Two invocations against the same --thread-dir: artifacts get .NNN
    suffixes, the index records both turns, and the second turn auto-resumes
    the prior thread_id by sending it as ``contextId`` on the message envelope."""
    thread_dir = tmp_path / "session"

    def _run_turn(query: str, narrative: str) -> FakeA2AServer:
        server = FakeA2AServer(events=happy_events(narrative))
        with server:
            run_a2a_session(
                SPEC,
                output="result.json",
                thread_dir=str(thread_dir),
                timeout=30,
                server=None,
                api_key=None,
                message_data={"q": query},
                artifact_to_result=_identity_artifact_to_result,
                build_summary=lambda result, narr: {"q": query, "narr": narr},
            )
        return server

    turn1 = _run_turn("first", "Turn 1 done.")
    turn2 = _run_turn("follow up", "Turn 2 done.")

    # Both files written with turn-suffixes; index has both turns + thread_id.
    assert (thread_dir / "result.001.json").exists()
    assert (thread_dir / "result.002.json").exists()
    index = json.loads((thread_dir / "index.json").read_text())
    assert index["thread_id"] == DEFAULT_THREAD_ID
    assert [t["turn"] for t in index["turns"]] == [1, 2]
    assert [t["summary"]["q"] for t in index["turns"]] == ["first", "follow up"]

    # Turn 1 had no contextId on the wire; turn 2 lifted the resumed thread_id.
    assert "contextId" not in turn1.requests[0]["params"]["message"]
    assert turn2.requests[0]["params"]["message"]["contextId"] == DEFAULT_THREAD_ID


def test_e2e_failed_terminal_raises_click_exception(tmp_path):
    out = tmp_path / "result.json"
    with FakeA2AServer(events=failed_events("Something exploded")):
        with pytest.raises(
            click.ClickException, match="TASK_STATE_FAILED.*Something exploded"
        ):
            run_a2a_session(
                SPEC,
                output=str(out),
                thread_dir=None,
                timeout=30,
                server=None,
                api_key=None,
                message_data={"q": "x"},
                artifact_to_result=_identity_artifact_to_result,
            )


def test_e2e_http_error_raises_click_exception(tmp_path):
    out = tmp_path / "result.json"
    with FakeA2AServer(status=401, body=b"unauthorized"):
        with pytest.raises(click.ClickException, match="HTTP 401"):
            run_a2a_session(
                SPEC,
                output=str(out),
                thread_dir=None,
                timeout=30,
                server=None,
                api_key=None,
                message_data={"q": "x"},
                artifact_to_result=_identity_artifact_to_result,
            )


# --- Resolver precedence ----------------------------------------------------


@pytest.mark.parametrize(
    "explicit,env,a2a_url,base_url,expected",
    [
        # Explicit flag wins; trailing slash is trimmed.
        (
            "http://explicit/",
            "http://env",
            "http://a2a",
            "http://base",
            "http://explicit",
        ),
        # Env var beats config.
        (None, "http://env/", "http://a2a", "http://base", "http://env"),
        # ``a2a_url`` config beats ``base_url``.
        (None, None, "http://a2a/", "http://base", "http://a2a"),
        # ``base_url`` is the last fallback.
        (None, None, None, "http://base/", "http://base"),
    ],
)
def test_resolve_server_precedence(
    monkeypatch, explicit, env, a2a_url, base_url, expected
):
    if env:
        monkeypatch.setenv(SPEC.env_var, env)
    else:
        monkeypatch.delenv(SPEC.env_var, raising=False)
    config: dict = {}
    if a2a_url is not None:
        config["a2a_url"] = a2a_url
    if base_url is not None:
        config["base_url"] = base_url
    with patch("asta.utils.a2a_interactive.get_api_config", return_value=config):
        assert _resolve_server(explicit, spec=SPEC) == expected


def test_resolve_api_key_precedence(monkeypatch):
    """Explicit > env > ``asta auth`` token > None (gateway-side auth allows missing)."""
    monkeypatch.setenv("ASTA_A2A_API_KEY", "env-key")
    # Explicit beats env.
    assert _resolve_api_key("explicit-key") == "explicit-key"
    # Env beats fallback.
    with patch("asta.utils.auth_helper.get_access_token", return_value="auth-token"):
        assert _resolve_api_key(None) == "env-key"
    # Asta-auth fallback when no explicit / no env.
    monkeypatch.delenv("ASTA_A2A_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    with patch("asta.utils.auth_helper.get_access_token", return_value="auth-token"):
        assert _resolve_api_key(None) == "auth-token"
    # No source available: returns None rather than raising.
    with patch(
        "asta.utils.auth_helper.get_access_token",
        side_effect=RuntimeError("not authenticated"),
    ):
        assert _resolve_api_key(None) is None
