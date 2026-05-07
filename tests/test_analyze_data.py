"""Tests for the `asta analyze-data` plugin."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli

CTX = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def _stub_auth(monkeypatch):
    monkeypatch.setattr(
        "asta.analyze_data.submit.get_access_token", lambda: "fake-token"
    )


def _stub_uploaded(filename: str, ctx: str = CTX) -> dict:
    return {
        "s3_uri": f"s3://bucket/userdata/u/context/{ctx}/{filename}",
        "filename": filename,
        "size": 10,
        "content_type": "text/csv",
    }


def _stub_send_response(ctx: str = CTX, task_id: str = "task-abc") -> dict:
    return {"id": task_id, "contextId": ctx, "status": {"state": "submitted"}}


class TestSubmitNewSession:
    """`submit` without --context-id mints a UUID and requires ≥1 file."""

    def test_uploads_files_and_sends_envelope(self, runner, tmp_path, monkeypatch):
        monkeypatch.delenv("ASTA_DV_MODAL_APP", raising=False)
        f1 = tmp_path / "sales.csv"
        f2 = tmp_path / "regions.csv"
        f1.write_text("a,b\n1,2\n")
        f2.write_text("x,y\n3,4\n")

        with (
            patch("asta.analyze_data.submit.upload_local_file") as up,
            patch("asta.analyze_data.submit.A2AClient") as Client,
        ):
            up.side_effect = [
                _stub_uploaded("sales.csv"),
                _stub_uploaded("regions.csv"),
            ]
            client = MagicMock()
            client.send_message.return_value = _stub_send_response()
            Client.return_value = client

            result = runner.invoke(
                cli, ["analyze-data", "submit", "the question", str(f1), str(f2)]
            )

        assert result.exit_code == 0, result.output

        # Both uploads happened against the *same* minted context_id.
        assert up.call_count == 2
        ctx_used = up.call_args_list[0].kwargs["context_id"]
        assert up.call_args_list[1].kwargs["context_id"] == ctx_used
        assert ctx_used != CTX  # newly minted, not the test's fixed UUID

        # send_message receives the envelope JSON + the same context_id.
        client.send_message.assert_called_once()
        sent_json, sent_kwargs = client.send_message.call_args
        envelope = json.loads(sent_json[0])
        assert envelope["kind"] == "analyze-data"
        tool_req = envelope["data"]["tool_request"]
        assert tool_req["query"] == "the question"
        assert tool_req["datasets"] == [
            f"s3://bucket/userdata/u/context/{CTX}/sales.csv",
            f"s3://bucket/userdata/u/context/{CTX}/regions.csv",
        ]
        assert tool_req["modal_app_name"] == "dv-core.prod"
        assert sent_kwargs["context_id"] == ctx_used

        # Stdout is the A2A response JSON.
        payload = json.loads(result.stdout)
        assert payload["id"] == "task-abc"

    def test_no_files_fails_without_context_id(self, runner):
        result = runner.invoke(cli, ["analyze-data", "submit", "the question"])
        assert result.exit_code != 0
        assert "context-id" in result.output.lower()

    def test_missing_file_fails_before_upload(self, runner):
        with patch("asta.analyze_data.submit.upload_local_file") as up:
            result = runner.invoke(
                cli,
                ["analyze-data", "submit", "the question", "/no/such/file.csv"],
            )
        assert result.exit_code != 0
        up.assert_not_called()


class TestSubmitContinuingSession:
    """`submit --context-id` reuses the session; files become optional."""

    def test_no_files_skips_upload(self, runner):
        with (
            patch("asta.analyze_data.submit.upload_local_file") as up,
            patch("asta.analyze_data.submit.A2AClient") as Client,
        ):
            client = MagicMock()
            client.send_message.return_value = _stub_send_response()
            Client.return_value = client

            result = runner.invoke(
                cli,
                [
                    "analyze-data",
                    "submit",
                    "--context-id",
                    CTX,
                    "follow-up question",
                ],
            )

        assert result.exit_code == 0, result.output
        up.assert_not_called()

        envelope = json.loads(client.send_message.call_args[0][0])
        tool_req = envelope["data"]["tool_request"]
        assert tool_req["query"] == "follow-up question"
        # Empty datasets are omitted so the dv-core schema default applies.
        assert "datasets" not in tool_req
        assert client.send_message.call_args.kwargs["context_id"] == CTX

    def test_files_attach_to_provided_context(self, runner, tmp_path):
        f = tmp_path / "extra.csv"
        f.write_text("p,q\n5,6\n")

        with (
            patch("asta.analyze_data.submit.upload_local_file") as up,
            patch("asta.analyze_data.submit.A2AClient") as Client,
        ):
            up.return_value = _stub_uploaded("extra.csv")
            client = MagicMock()
            client.send_message.return_value = _stub_send_response()
            Client.return_value = client

            result = runner.invoke(
                cli,
                [
                    "analyze-data",
                    "submit",
                    "--context-id",
                    CTX,
                    "follow-up with new file",
                    str(f),
                ],
            )

        assert result.exit_code == 0, result.output
        assert up.call_args.kwargs["context_id"] == CTX

        envelope = json.loads(client.send_message.call_args[0][0])
        assert envelope["data"]["tool_request"]["datasets"] == [
            f"s3://bucket/userdata/u/context/{CTX}/extra.csv"
        ]


class TestModalAppRouting:
    def test_default_routes_to_prod(self, runner, tmp_path, monkeypatch):
        monkeypatch.delenv("ASTA_DV_MODAL_APP", raising=False)
        f = tmp_path / "x.csv"
        f.write_text("x")

        with (
            patch("asta.analyze_data.submit.upload_local_file") as up,
            patch("asta.analyze_data.submit.A2AClient") as Client,
        ):
            up.return_value = _stub_uploaded("x.csv")
            client = MagicMock()
            client.send_message.return_value = _stub_send_response()
            Client.return_value = client

            result = runner.invoke(cli, ["analyze-data", "submit", "q", str(f)])

        assert result.exit_code == 0, result.output
        envelope = json.loads(client.send_message.call_args[0][0])
        assert envelope["data"]["tool_request"]["modal_app_name"] == "dv-core.prod"

    def test_env_var_overrides(self, runner, tmp_path, monkeypatch):
        monkeypatch.setenv("ASTA_DV_MODAL_APP", "dv-core.regan")
        f = tmp_path / "x.csv"
        f.write_text("x")

        with (
            patch("asta.analyze_data.submit.upload_local_file") as up,
            patch("asta.analyze_data.submit.A2AClient") as Client,
        ):
            up.return_value = _stub_uploaded("x.csv")
            client = MagicMock()
            client.send_message.return_value = _stub_send_response()
            Client.return_value = client

            result = runner.invoke(cli, ["analyze-data", "submit", "q", str(f)])

        assert result.exit_code == 0, result.output
        envelope = json.loads(client.send_message.call_args[0][0])
        assert envelope["data"]["tool_request"]["modal_app_name"] == "dv-core.regan"


class TestSubmitOutput:
    def test_output_path_writes_file(self, runner, tmp_path, monkeypatch):
        monkeypatch.delenv("ASTA_DV_MODAL_APP", raising=False)
        f = tmp_path / "x.csv"
        f.write_text("x")
        out = tmp_path / "response.json"

        with (
            patch("asta.analyze_data.submit.upload_local_file") as up,
            patch("asta.analyze_data.submit.A2AClient") as Client,
        ):
            up.return_value = _stub_uploaded("x.csv")
            client = MagicMock()
            client.send_message.return_value = _stub_send_response()
            Client.return_value = client

            result = runner.invoke(
                cli,
                ["analyze-data", "submit", "--output", str(out), "q", str(f)],
            )

        assert result.exit_code == 0, result.output
        assert out.exists()
        assert json.loads(out.read_text())["id"] == "task-abc"


class TestGroupWiring:
    def test_analyze_data_help_lists_subcommands(self, runner):
        result = runner.invoke(cli, ["analyze-data", "--help"])
        assert result.exit_code == 0
        for sub in ("card", "send-message", "task", "submit", "poll"):
            assert sub in result.output
        # `upload` was folded into `submit` and is no longer exposed.
        assert "  upload" not in result.output


class TestConfig:
    def test_api_config_resolves_base_url(self):
        from asta.utils.config import get_api_config

        cfg = get_api_config("analyze_data")
        assert "base_url" in cfg
        assert cfg["base_url"].endswith("/api/analyze-data") or cfg[
            "base_url"
        ].startswith("http")


class TestUploadHelper:
    """Exercise the shared helper directly — verifies the GET + PUT shape."""

    def test_upload_local_file_emits_presign_get_and_put(self, tmp_path):
        from asta.analyze_data import _upload as upload_mod

        f = tmp_path / "hello.csv"
        f.write_text("x,y\n1,2\n")

        presign_body = json.dumps(
            {
                "s3_uri": f"s3://b/userdata/auth0|u/context/{CTX}/hello.csv",
                "upload_url": "https://s3.example/presigned?sig=abc",
                "expires_in": 3600,
                "content_type": "text/csv",
            }
        ).encode()

        calls: list = []

        def fake_urlopen(req, timeout=None):
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "headers": dict(req.headers),
                }
            )
            resp = MagicMock()
            if req.get_method() == "GET":
                resp.read.return_value = presign_body
            else:
                resp.read.return_value = b""
            resp.__enter__ = lambda self: self
            resp.__exit__ = lambda self, *a: None
            return resp

        with patch(
            "asta.analyze_data._upload.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = upload_mod.upload_local_file(
                "http://dv.local", "tok", str(f), context_id=CTX
            )

        assert result["s3_uri"] == f"s3://b/userdata/auth0|u/context/{CTX}/hello.csv"
        assert result["content_type"] == "text/csv"
        assert len(calls) == 2

        get_call, put_call = calls
        assert get_call["method"] == "GET"
        assert "/upload_url?" in get_call["url"]
        assert "filename=hello.csv" in get_call["url"]
        assert f"context_id={CTX}" in get_call["url"]
        assert get_call["headers"].get("Authorization") == "Bearer tok"

        assert put_call["method"] == "PUT"
        assert put_call["url"] == "https://s3.example/presigned?sig=abc"
        assert put_call["headers"].get("Content-type") == "text/csv"

    def test_upload_local_file_rejects_missing(self, tmp_path):
        from asta.analyze_data import _upload as upload_mod

        with pytest.raises(FileNotFoundError):
            upload_mod.upload_local_file(
                "http://dv.local", "tok", str(tmp_path / "nope.csv"), context_id=CTX
            )

    def test_upload_local_file_rejects_path_traversal(self, tmp_path):
        from asta.analyze_data import _upload as upload_mod

        # The os.path.basename of a traversal-style path on the *server side*
        # is what dv-core enforces, but we still defensively reject `..` in
        # the resolved basename.
        evil = tmp_path / ".."
        with pytest.raises((FileNotFoundError, ValueError)):
            upload_mod.upload_local_file(
                "http://dv.local", "tok", str(evil), context_id=CTX
            )
