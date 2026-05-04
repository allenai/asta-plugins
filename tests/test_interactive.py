"""Tests for `asta literature interactive` (CLI + SSE consumer).

Mirrors the patterns in ``test_cli.py`` (CliRunner with the network layer mocked)
and ``test_client.py`` (mock the HTTP boundary, exercise client logic).
"""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.literature.interactive import (
    _build_rpc_body,
    _resolve_api_key,
    _resolve_server,
    _run_interactive,
)

# --- Fixtures and helpers ----------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


def _stream_event(payload: dict) -> str:
    """Encode a single SSE ``data:`` line as the server emits."""
    return f"data: {json.dumps(payload)}"


def _initial_task_event(thread_id: str = "thrd:abc") -> dict:
    return {
        "result": {
            "task": {
                "id": "task-1",
                "contextId": "ctx-1",
                "status": {"state": "TASK_STATE_SUBMITTED"},
                "metadata": {"thread_id": thread_id},
            }
        },
        "id": "stream",
        "jsonrpc": "2.0",
    }


def _working_step_event(short_desc: str, run_state: str = "running") -> dict:
    return {
        "result": {
            "statusUpdate": {
                "taskId": "task-1",
                "contextId": "ctx-1",
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
                                    "run_state": run_state,
                                }
                            },
                        ]
                    },
                },
            }
        },
        "id": "stream",
        "jsonrpc": "2.0",
    }


def _artifact_event(thread_id: str = "thrd:abc") -> dict:
    return {
        "result": {
            "artifactUpdate": {
                "taskId": "task-1",
                "contextId": "ctx-1",
                "metadata": {"thread_id": thread_id},
                "artifact": {
                    "artifactId": "task-1",
                    "name": "Paper Finder Results",
                    "description": "All done.",
                    "parts": [
                        {
                            "data": {
                                "schemaVersion": "1",
                                "subtype": "paper-finder-search-result",
                                "entities": {
                                    "ent_001": {
                                        "id": "ent_001",
                                        "type": "PAPER",
                                        "displayLabel": "Foo",
                                        "s2Metadata": {
                                            "title": "Foo: A Paper",
                                            "year": 2024,
                                            "venue": "NeurIPS",
                                            "corpusId": "12345",
                                            "authors": [
                                                {"name": "Alice", "authorId": "a1"}
                                            ],
                                        },
                                        "url": "https://s2/12345",
                                        "citationCount": 7,
                                        "relevanceScore": 0.91,
                                    }
                                },
                            }
                        }
                    ],
                },
            }
        },
        "id": "stream",
        "jsonrpc": "2.0",
    }


def _terminal_completed_event(narrative: str = "Found 1 paper.") -> dict:
    return {
        "result": {
            "statusUpdate": {
                "taskId": "task-1",
                "contextId": "ctx-1",
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "message": {"parts": [{"text": narrative}]},
                },
                "metadata": {"thread_id": "thrd:abc"},
            }
        },
        "id": "stream",
        "jsonrpc": "2.0",
    }


def _terminal_failed_event(narrative: str = "Boom.") -> dict:
    return {
        "result": {
            "statusUpdate": {
                "taskId": "task-1",
                "contextId": "ctx-1",
                "status": {
                    "state": "TASK_STATE_FAILED",
                    "message": {"parts": [{"text": narrative}]},
                },
            }
        },
        "id": "stream",
        "jsonrpc": "2.0",
    }


class _FakeStreamResponse:
    """Mimics the async-context-manager + aiter_lines + status_code surface
    that ``httpx.AsyncClient.stream(...)`` returns."""

    def __init__(self, lines: list[str], status_code: int = 200, body: bytes = b""):
        self._lines = lines
        self.status_code = status_code
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body


def _patch_httpx_stream(events: list[dict]):
    """Patch ``httpx.AsyncClient`` so .stream() returns a fake SSE stream of `events`."""
    lines = [_stream_event(ev) for ev in events]

    fake_response = _FakeStreamResponse(lines)
    fake_client = MagicMock()
    fake_client.stream = MagicMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    return patch(
        "asta.literature.interactive.httpx.AsyncClient", return_value=fake_client
    ), fake_client


# --- _build_rpc_body ---------------------------------------------------------


class TestBuildRpcBody:
    def test_omits_thread_id_when_none(self):
        body = _build_rpc_body("hello", "fast", None)
        assert body["method"] == "SendStreamingMessage"
        assert body["jsonrpc"] == "2.0"
        data = body["params"]["message"]["parts"][0]["data"]["data"]
        assert data == {"query": "hello", "operation_mode": "fast"}

    def test_includes_thread_id_when_set(self):
        body = _build_rpc_body("hello", "infer", "thrd:xyz")
        data = body["params"]["message"]["parts"][0]["data"]["data"]
        assert data["thread_id"] == "thrd:xyz"
        assert data["query"] == "hello"
        assert data["operation_mode"] == "infer"

    def test_role_is_user(self):
        body = _build_rpc_body("q", "fast", None)
        assert body["params"]["message"]["role"] == "ROLE_USER"

    def test_omits_context_id_when_no_thread_id(self):
        """Fresh conversations don't have a contextId yet; the server generates one."""
        body = _build_rpc_body("hello", "fast", None)
        assert "contextId" not in body["params"]["message"]

    def test_sets_context_id_to_thread_id_when_continuing(self):
        """A2A's ``contextId`` groups messages in a conversation. Mabool uses
        ``thread_id`` for the same purpose, so we send the same value on both."""
        body = _build_rpc_body("follow up", "fast", "thrd:xyz")
        message = body["params"]["message"]
        assert message["contextId"] == "thrd:xyz"
        # The data-part thread_id is still set — both routes carry the same id.
        assert message["parts"][0]["data"]["data"]["thread_id"] == "thrd:xyz"


# --- _resolve_server / _resolve_api_key --------------------------------------


class TestResolveServer:
    def test_explicit_server_wins(self, monkeypatch):
        monkeypatch.setenv("ASTA_PAPER_FINDER_A2A_URL", "http://env-host")
        assert _resolve_server("http://explicit/") == "http://explicit"

    def test_env_var_used_when_no_flag(self, monkeypatch):
        monkeypatch.setenv("ASTA_PAPER_FINDER_A2A_URL", "http://env-host/")
        with patch(
            "asta.literature.interactive.get_api_config", return_value={"base_url": "x"}
        ):
            assert _resolve_server(None) == "http://env-host"

    def test_falls_back_to_a2a_url_config(self, monkeypatch):
        monkeypatch.delenv("ASTA_PAPER_FINDER_A2A_URL", raising=False)
        with patch(
            "asta.literature.interactive.get_api_config",
            return_value={"a2a_url": "http://cfg-host/", "base_url": "http://other"},
        ):
            assert _resolve_server(None) == "http://cfg-host"

    def test_falls_back_to_base_url(self, monkeypatch):
        monkeypatch.delenv("ASTA_PAPER_FINDER_A2A_URL", raising=False)
        with patch(
            "asta.literature.interactive.get_api_config",
            return_value={"base_url": "http://b/"},
        ):
            assert _resolve_server(None) == "http://b"


class TestResolveApiKey:
    def test_explicit_wins(self, monkeypatch):
        monkeypatch.setenv("ASTA_A2A_API_KEY", "env-key")
        assert _resolve_api_key("explicit-key") == "explicit-key"

    def test_env_var_used(self, monkeypatch):
        monkeypatch.setenv("ASTA_A2A_API_KEY", "env-key")
        assert _resolve_api_key(None) == "env-key"

    def test_falls_back_to_asta_auth(self, monkeypatch):
        monkeypatch.delenv("ASTA_A2A_API_KEY", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        with patch(
            "asta.utils.auth_helper.get_access_token", return_value="auth-token"
        ):
            assert _resolve_api_key(None) == "auth-token"

    def test_returns_none_when_no_auth_available(self, monkeypatch):
        """Auth is gateway-enforced; an unauth'd backend is allowed, so missing
        creds must resolve to None rather than raise."""
        monkeypatch.delenv("ASTA_A2A_API_KEY", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        with patch(
            "asta.utils.auth_helper.get_access_token",
            side_effect=RuntimeError("not authenticated"),
        ):
            assert _resolve_api_key(None) is None


# --- _run_interactive: the SSE consumer --------------------------------------


class TestRunInteractive:
    """Drive the SSE consumer with a hand-crafted event stream."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        events = [
            _initial_task_event(),
            _working_step_event("Running keyword search"),
            _working_step_event("Reranking"),
            _artifact_event(),
            _terminal_completed_event("Found 1 paper."),
        ]
        patcher, _ = _patch_httpx_stream(events)
        with patcher:
            result = await _run_interactive(
                query="q",
                mode="fast",
                thread_id=None,
                server="http://srv",
                api_key="k",
                timeout=30,
            )
        assert result["thread_id"] == "thrd:abc"
        assert result["narrative"] == "Found 1 paper."
        assert result["artifact"]["schemaVersion"] == "1"
        assert "ent_001" in result["artifact"]["entities"]

    @pytest.mark.asyncio
    async def test_failed_terminal_state_raises(self):
        events = [
            _initial_task_event(),
            _terminal_failed_event("Bad things"),
        ]
        patcher, _ = _patch_httpx_stream(events)
        with patcher:
            with pytest.raises(click.ClickException) as exc_info:
                await _run_interactive(
                    query="q",
                    mode="fast",
                    thread_id=None,
                    server="http://srv",
                    api_key="k",
                    timeout=30,
                )
            assert "TASK_STATE_FAILED" in exc_info.value.message
            assert "Bad things" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_missing_artifact_raises(self):
        events = [
            _initial_task_event(),
            _terminal_completed_event(),
        ]
        patcher, _ = _patch_httpx_stream(events)
        with patcher:
            with pytest.raises(click.ClickException, match="no artifact"):
                await _run_interactive(
                    query="q",
                    mode="fast",
                    thread_id=None,
                    server="http://srv",
                    api_key="k",
                    timeout=30,
                )

    @pytest.mark.asyncio
    async def test_no_terminal_state_raises(self):
        events = [_initial_task_event(), _artifact_event()]
        patcher, _ = _patch_httpx_stream(events)
        with patcher:
            with pytest.raises(click.ClickException, match="terminal status"):
                await _run_interactive(
                    query="q",
                    mode="fast",
                    thread_id=None,
                    server="http://srv",
                    api_key="k",
                    timeout=30,
                )

    @pytest.mark.asyncio
    async def test_thread_id_round_trip_uses_client_value_when_provided(self):
        """When the client sends a thread_id, the server (real mabool) echoes the
        same one. Verify our parser captures it from any of the events."""
        client_thread = "thrd:client-supplied"
        events = [
            _initial_task_event(thread_id=client_thread),
            _artifact_event(thread_id=client_thread),
            _terminal_completed_event(),
        ]
        patcher, _ = _patch_httpx_stream(events)
        with patcher:
            result = await _run_interactive(
                query="follow up",
                mode="fast",
                thread_id=client_thread,
                server="http://srv",
                api_key="k",
                timeout=30,
            )
        assert result["thread_id"] == client_thread

    @pytest.mark.asyncio
    async def test_authorization_header_set_when_api_key_provided(self):
        events = [
            _initial_task_event(),
            _artifact_event(),
            _terminal_completed_event(),
        ]
        patcher, fake_client = _patch_httpx_stream(events)
        with patcher:
            await _run_interactive(
                query="q",
                mode="fast",
                thread_id=None,
                server="http://srv",
                api_key="bearer-xyz",
                timeout=30,
            )
        sent_headers = fake_client.stream.call_args.kwargs["headers"]
        assert sent_headers["Authorization"] == "Bearer bearer-xyz"
        assert sent_headers["A2A-Version"] == "1.0"

    @pytest.mark.asyncio
    async def test_no_authorization_header_when_api_key_is_none(self):
        """Auth is gateway-enforced; the client must omit Authorization when no
        bearer is configured, so unauth'd local backends work."""
        events = [
            _initial_task_event(),
            _artifact_event(),
            _terminal_completed_event(),
        ]
        patcher, fake_client = _patch_httpx_stream(events)
        with patcher:
            await _run_interactive(
                query="q",
                mode="fast",
                thread_id=None,
                server="http://srv",
                api_key=None,
                timeout=30,
            )
        sent_headers = fake_client.stream.call_args.kwargs["headers"]
        assert "Authorization" not in sent_headers

    @pytest.mark.asyncio
    async def test_http_error_raises_with_body(self):
        fake_response = _FakeStreamResponse(
            lines=[], status_code=401, body=b"unauthorized"
        )
        fake_client = MagicMock()
        fake_client.stream = MagicMock(return_value=fake_response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        with patch(
            "asta.literature.interactive.httpx.AsyncClient", return_value=fake_client
        ):
            with pytest.raises(click.ClickException, match="HTTP 401"):
                await _run_interactive(
                    query="q",
                    mode="fast",
                    thread_id=None,
                    server="http://srv",
                    api_key="k",
                    timeout=30,
                )


# --- CLI-level tests (mirror TestFindCommand in test_cli.py) -----------------


class TestInteractiveCommand:
    def test_missing_query(self, runner):
        result = runner.invoke(cli, ["literature", "interactive"])
        assert result.exit_code != 0

    def test_missing_output_required(self, runner):
        result = runner.invoke(cli, ["literature", "interactive", "test query"])
        assert result.exit_code != 0
        assert "output" in result.output.lower() or "-o" in result.output.lower()

    def test_success_writes_literature_search_result(self, runner, tmp_path):
        fake_run = AsyncMock(
            return_value={
                "artifact": {
                    "schemaVersion": "1",
                    "entities": {
                        "ent_001": {
                            "id": "ent_001",
                            "type": "PAPER",
                            "displayLabel": "Foo",
                            "s2Metadata": {
                                "title": "Foo: A Paper",
                                "year": 2024,
                                "venue": "NeurIPS",
                                "corpusId": "12345",
                                "authors": [{"name": "Alice", "authorId": "a1"}],
                            },
                            "url": "https://s2/12345",
                            "citationCount": 7,
                            "relevanceScore": 0.91,
                        }
                    },
                },
                "thread_id": "thrd:abc",
                "narrative": "Found 1 paper.",
            }
        )
        output_file = tmp_path / "results.json"
        with patch("asta.literature.interactive._run_interactive", fake_run):
            with patch(
                "asta.literature.interactive._resolve_api_key",
                return_value="fake-token",
            ):
                with patch(
                    "asta.literature.interactive._resolve_server",
                    return_value="http://srv",
                ):
                    result = runner.invoke(
                        cli,
                        [
                            "literature",
                            "interactive",
                            "transformer survey",
                            "-o",
                            str(output_file),
                        ],
                    )

        assert result.exit_code == 0, result.output
        assert output_file.exists()
        with open(output_file) as f:
            data = json.load(f)
        assert data["query"] == "transformer survey"
        assert data["thread_id"] == "thrd:abc"
        assert data["narrative"] == "Found 1 paper."
        assert len(data["results"]) == 1
        assert data["results"][0]["corpusId"] == 12345
        # Reports the thread_id on stderr-equivalent for the user to copy
        assert "thrd:abc" in result.output

    def test_passes_thread_id_through(self, runner, tmp_path):
        captured = {}

        async def fake_run(**kwargs):
            captured.update(kwargs)
            return {
                "artifact": {"schemaVersion": "1", "entities": {}},
                "thread_id": kwargs["thread_id"],
                "narrative": "ok",
            }

        output_file = tmp_path / "results.json"
        with patch(
            "asta.literature.interactive._run_interactive", side_effect=fake_run
        ):
            with patch(
                "asta.literature.interactive._resolve_api_key",
                return_value="fake-token",
            ):
                with patch(
                    "asta.literature.interactive._resolve_server",
                    return_value="http://srv",
                ):
                    result = runner.invoke(
                        cli,
                        [
                            "literature",
                            "interactive",
                            "follow up",
                            "--thread-id",
                            "thrd:resume",
                            "-o",
                            str(output_file),
                        ],
                    )

        assert result.exit_code == 0, result.output
        assert captured["thread_id"] == "thrd:resume"
        assert captured["mode"] == "infer"  # default

    def test_passes_mode_and_timeout(self, runner, tmp_path):
        captured = {}

        async def fake_run(**kwargs):
            captured.update(kwargs)
            return {
                "artifact": {"schemaVersion": "1", "entities": {}},
                "thread_id": None,
                "narrative": None,
            }

        output_file = tmp_path / "results.json"
        with patch(
            "asta.literature.interactive._run_interactive", side_effect=fake_run
        ):
            with patch(
                "asta.literature.interactive._resolve_api_key",
                return_value="fake-token",
            ):
                with patch(
                    "asta.literature.interactive._resolve_server",
                    return_value="http://srv",
                ):
                    result = runner.invoke(
                        cli,
                        [
                            "literature",
                            "interactive",
                            "q",
                            "-o",
                            str(output_file),
                            "--mode",
                            "diligent",
                            "--timeout",
                            "120",
                        ],
                    )

        assert result.exit_code == 0, result.output
        assert captured["mode"] == "diligent"
        assert captured["timeout"] == 120

    def test_invalid_mode_rejected(self, runner, tmp_path):
        output_file = tmp_path / "results.json"
        result = runner.invoke(
            cli,
            [
                "literature",
                "interactive",
                "q",
                "-o",
                str(output_file),
                "--mode",
                "bogus",
            ],
        )
        assert result.exit_code != 0

    def test_general_error_exits_with_clickexception(self, runner, tmp_path):
        async def boom(**_):
            raise RuntimeError("kaboom")

        output_file = tmp_path / "results.json"
        with patch(
            "asta.literature.interactive._run_interactive", side_effect=boom
        ):
            with patch(
                "asta.literature.interactive._resolve_api_key",
                return_value="fake-token",
            ):
                with patch(
                    "asta.literature.interactive._resolve_server",
                    return_value="http://srv",
                ):
                    result = runner.invoke(
                        cli, ["literature", "interactive", "q", "-o", str(output_file)]
                    )

        assert result.exit_code != 0
        assert "kaboom" in result.output


# --- --thread-dir mode ------------------------------------------------------


class TestThreadDirMode:
    """Persisted multi-turn flow: each invocation writes DIR/<stem>.NNN.<ext>
    plus DIR/index.json, and resumes thread_id automatically on later calls."""

    @staticmethod
    def _fake_run(thread_id_returned: str = "thrd:abc"):
        async def _run(**kwargs):
            return {
                "artifact": {
                    "schemaVersion": "1",
                    "entities": {
                        "ent_001": {
                            "id": "ent_001",
                            "type": "PAPER",
                            "displayLabel": "Foo",
                            "s2Metadata": {
                                "title": "Foo: A Paper",
                                "year": 2024,
                                "corpusId": "12345",
                                "authors": [{"name": "Alice", "authorId": "a1"}],
                            },
                            "relevanceScore": 0.91,
                        }
                    },
                },
                "thread_id": thread_id_returned,
                "narrative": "Found 1 paper.",
            }

        return _run

    def _invoke(self, runner, fake_run, *args):
        with patch(
            "asta.literature.interactive._run_interactive", side_effect=fake_run
        ):
            with patch(
                "asta.literature.interactive._resolve_api_key",
                return_value="fake-token",
            ):
                with patch(
                    "asta.literature.interactive._resolve_server",
                    return_value="http://srv",
                ):
                    return runner.invoke(cli, list(args))

    def test_first_turn_creates_index_and_suffixed_artifact(self, runner, tmp_path):
        thread_dir = tmp_path / "session"
        result = self._invoke(
            runner,
            self._fake_run(),
            "literature",
            "interactive",
            "transformer survey",
            "--thread-dir",
            str(thread_dir),
            "-o",
            "transformer-survey.json",
        )
        assert result.exit_code == 0, result.output
        assert (thread_dir / "transformer-survey.001.json").exists()
        assert (thread_dir / "index.json").exists()

        index = json.loads((thread_dir / "index.json").read_text())
        assert index["thread_id"] == "thrd:abc"
        assert len(index["turns"]) == 1
        assert index["turns"][0] == {
            "turn": 1,
            "ts": index["turns"][0]["ts"],
            "query": "transformer survey",
            "mode": "infer",
            "narrative_excerpt": "Found 1 paper.",
            "paper_count": 1,
            "file": "transformer-survey.001.json",
        }

    def test_second_turn_resumes_thread_id_and_increments_suffix(
        self, runner, tmp_path
    ):
        thread_dir = tmp_path / "session"
        captured: list[dict] = []

        async def fake_run(**kwargs):
            captured.append(kwargs)
            return {
                "artifact": {"schemaVersion": "1", "entities": {}},
                "thread_id": "thrd:abc",
                "narrative": "ok",
            }

        # turn 1
        result1 = self._invoke(
            runner,
            fake_run,
            "literature",
            "interactive",
            "first",
            "--thread-dir",
            str(thread_dir),
            "-o",
            "results.json",
        )
        assert result1.exit_code == 0, result1.output

        # turn 2 — no --thread-id passed; CLI should auto-resume from index.json
        result2 = self._invoke(
            runner,
            fake_run,
            "literature",
            "interactive",
            "second",
            "--thread-dir",
            str(thread_dir),
            "-o",
            "results.json",
        )
        assert result2.exit_code == 0, result2.output

        # _run_interactive was called twice; the second call carried the resumed thread_id
        assert len(captured) == 2
        assert captured[0]["thread_id"] is None
        assert captured[1]["thread_id"] == "thrd:abc"

        assert (thread_dir / "results.001.json").exists()
        assert (thread_dir / "results.002.json").exists()
        index = json.loads((thread_dir / "index.json").read_text())
        assert [t["turn"] for t in index["turns"]] == [1, 2]
        assert [t["query"] for t in index["turns"]] == ["first", "second"]
        assert [t["file"] for t in index["turns"]] == [
            "results.001.json",
            "results.002.json",
        ]

    def test_explicit_thread_id_mismatch_errors(self, runner, tmp_path):
        thread_dir = tmp_path / "session"
        # Seed an index with one turn for thread X
        result1 = self._invoke(
            runner,
            self._fake_run("thrd:X"),
            "literature",
            "interactive",
            "first",
            "--thread-dir",
            str(thread_dir),
            "-o",
            "results.json",
        )
        assert result1.exit_code == 0

        # Now try to continue with --thread-id Y — should error
        result2 = self._invoke(
            runner,
            self._fake_run("thrd:X"),
            "literature",
            "interactive",
            "second",
            "--thread-dir",
            str(thread_dir),
            "--thread-id",
            "thrd:Y",
            "-o",
            "results.json",
        )
        assert result2.exit_code != 0
        assert "disagrees" in result2.output

    def test_thread_dir_requires_basename_output(self, runner, tmp_path):
        thread_dir = tmp_path / "session"
        result = self._invoke(
            runner,
            self._fake_run(),
            "literature",
            "interactive",
            "q",
            "--thread-dir",
            str(thread_dir),
            "-o",
            "/abs/path/not-allowed.json",
        )
        assert result.exit_code != 0
        assert "basename" in result.output

    def test_thread_dir_uses_meaningful_names(self, runner, tmp_path):
        """The user wanted artifacts to keep meaningful names with a suffix —
        not generic ``turn_NNN.json``."""
        thread_dir = tmp_path / "session"
        result = self._invoke(
            runner,
            self._fake_run(),
            "literature",
            "interactive",
            "q",
            "--thread-dir",
            str(thread_dir),
            "-o",
            "transformer-survey.json",
        )
        assert result.exit_code == 0, result.output
        # The user-provided stem is preserved; only the turn suffix is added.
        assert (thread_dir / "transformer-survey.001.json").exists()
        assert not (thread_dir / "turn_001.json").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
