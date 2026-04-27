"""Tests for the `asta data-analysis` plugin."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def _stub_auth(monkeypatch):
    # Skip the real token resolution in every test; _get_api_key is imported
    # into both analyze.py and upload.py.
    monkeypatch.setattr("asta.data_analysis.analyze._get_api_key", lambda k: "fake-token")
    monkeypatch.setattr("asta.data_analysis.upload._get_api_key", lambda k: "fake-token")


class TestAnalyze:
    def test_single_local_path(self, runner, tmp_path):
        f = tmp_path / "titanic.csv"
        f.write_text("a,b\n1,2\n")

        with patch("asta.data_analysis.analyze.upload_local_file") as up, patch(
            "asta.data_analysis.analyze.A2AClient"
        ) as A2A:
            up.return_value = {
                "s3_uri": "s3://ai2-asta-workspaces/userdata/auth0|u/titanic.csv",
                "filename": "titanic.csv",
                "size": 10,
                "content_type": "text/csv",
            }
            client = A2A.return_value
            client.send_message.return_value = {"id": "task-123", "status": {"state": "submitted"}}

            result = runner.invoke(
                cli,
                ["data-analysis", "analyze", str(f), "--query", "What's interesting?"],
            )

        assert result.exit_code == 0, result.output
        up.assert_called_once()
        client.send_message.assert_called_once()

        sent_json = client.send_message.call_args.args[0]
        sent = json.loads(sent_json)
        assert sent["kind"] == "analyze-data"
        assert sent["data"]["tool_request"]["query"] == "What's interesting?"
        assert sent["data"]["tool_request"]["datasets"] == [
            "s3://ai2-asta-workspaces/userdata/auth0|u/titanic.csv"
        ]
        assert "task-123" in result.output

    def test_multiple_local_paths_preserve_order(self, runner, tmp_path):
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("x")
        b.write_text("y")

        with patch("asta.data_analysis.analyze.upload_local_file") as up, patch(
            "asta.data_analysis.analyze.A2AClient"
        ) as A2A:
            up.side_effect = [
                {"s3_uri": "s3://b/a.csv", "filename": "a.csv", "size": 1, "content_type": "text/csv"},
                {"s3_uri": "s3://b/b.csv", "filename": "b.csv", "size": 1, "content_type": "text/csv"},
            ]
            A2A.return_value.send_message.return_value = {"id": "t"}

            result = runner.invoke(
                cli,
                ["data-analysis", "analyze", str(a), str(b), "--query", "Compare"],
            )

        assert result.exit_code == 0, result.output
        sent = json.loads(A2A.return_value.send_message.call_args.args[0])
        assert sent["data"]["tool_request"]["datasets"] == ["s3://b/a.csv", "s3://b/b.csv"]

    def test_missing_file_fails_before_upload(self, runner):
        with patch("asta.data_analysis.analyze.upload_local_file") as up:
            result = runner.invoke(
                cli,
                ["data-analysis", "analyze", "/no/such/file.csv", "--query", "q"],
            )
        assert result.exit_code != 0
        up.assert_not_called()

    def test_over_5gb_fails_fast(self, runner, tmp_path):
        f = tmp_path / "huge.csv"
        f.write_text("x")

        with patch("asta.data_analysis.analyze.upload_local_file") as up, patch(
            "asta.data_analysis.analyze.A2AClient"
        ) as A2A:
            up.side_effect = ValueError(
                "File is 6.00 GiB; single-PUT uploads are limited to 5 GiB."
            )

            result = runner.invoke(
                cli, ["data-analysis", "analyze", str(f), "--query", "q"]
            )

        assert result.exit_code != 0
        assert "5 GiB" in result.output
        A2A.return_value.send_message.assert_not_called()

    def test_requires_query(self, runner, tmp_path):
        f = tmp_path / "x.csv"
        f.write_text("x")
        result = runner.invoke(cli, ["data-analysis", "analyze", str(f)])
        assert result.exit_code != 0

    def test_requires_dataset(self, runner):
        result = runner.invoke(cli, ["data-analysis", "analyze", "--query", "q"])
        assert result.exit_code != 0


class TestUpload:
    def test_happy_path_prints_tag_and_uri(self, runner, tmp_path):
        f = tmp_path / "x.csv"
        f.write_text("x")

        with patch("asta.data_analysis.upload.upload_local_file") as up:
            up.return_value = {
                "s3_uri": "s3://bucket/userdata/u/x.csv",
                "filename": "x.csv",
                "size": 1,
                "content_type": "text/csv",
            }
            result = runner.invoke(cli, ["data-analysis", "upload", str(f)])

        assert result.exit_code == 0, result.output
        assert "s3_uri: s3://bucket/userdata/u/x.csv" in result.output
        assert '<astaattachment s3_uri="s3://bucket/userdata/u/x.csv">x.csv</astaattachment>' in result.output

    def test_json_output(self, runner, tmp_path):
        f = tmp_path / "x.csv"
        f.write_text("x")

        with patch("asta.data_analysis.upload.upload_local_file") as up:
            up.return_value = {
                "s3_uri": "s3://bucket/userdata/u/x.csv",
                "filename": "x.csv",
                "size": 1,
                "content_type": "text/csv",
            }
            result = runner.invoke(cli, ["data-analysis", "upload", str(f), "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["s3_uri"] == "s3://bucket/userdata/u/x.csv"
        assert payload["filename"] == "x.csv"
        assert "attachment_tag" in payload
        assert payload["size"] == 1
        assert payload["content_type"] == "text/csv"


class TestGroupWiring:
    def test_data_analysis_help_lists_all_subcommands(self, runner):
        result = runner.invoke(cli, ["data-analysis", "--help"])
        assert result.exit_code == 0
        for sub in ("card", "send-message", "task", "analyze", "upload"):
            assert sub in result.output


class TestConfig:
    def test_api_config_resolves_base_url(self):
        from asta.utils.config import get_api_config

        cfg = get_api_config("data_analysis")
        assert "base_url" in cfg
        assert cfg["base_url"].endswith("/api/data-analysis") or cfg["base_url"].startswith("http")


class TestUploadHelper:
    """Exercise the shared helper directly — verifies the GET + PUT shape."""

    def test_upload_local_file_emits_presign_get_and_put(self, tmp_path):
        from asta.data_analysis import _client

        f = tmp_path / "hello.csv"
        f.write_text("x,y\n1,2\n")

        presign_body = json.dumps(
            {
                "s3_uri": "s3://b/userdata/auth0|u/hello.csv",
                "upload_url": "https://s3.example/presigned?sig=abc",
                "expires_in": 3600,
                "content_type": "text/csv",
            }
        ).encode()

        calls: list = []

        def fake_urlopen(req, timeout=None):
            calls.append({"url": req.full_url, "method": req.get_method(), "headers": dict(req.headers)})
            resp = MagicMock()
            if req.get_method() == "GET":
                resp.read.return_value = presign_body
            else:
                resp.read.return_value = b""
            resp.__enter__ = lambda self: self
            resp.__exit__ = lambda self, *a: None
            return resp

        with patch("asta.data_analysis._client.urllib.request.urlopen", side_effect=fake_urlopen):
            result = _client.upload_local_file("http://dv.local", "tok", str(f))

        assert result["s3_uri"] == "s3://b/userdata/auth0|u/hello.csv"
        assert result["content_type"] == "text/csv"
        assert len(calls) == 2

        get_call, put_call = calls
        assert get_call["method"] == "GET"
        assert "/upload_url?" in get_call["url"]
        assert "filename=hello.csv" in get_call["url"]
        # urllib normalizes header names to Title-Case
        assert get_call["headers"].get("Authorization") == "Bearer tok"

        assert put_call["method"] == "PUT"
        assert put_call["url"] == "https://s3.example/presigned?sig=abc"
        assert put_call["headers"].get("Content-type") == "text/csv"

    def test_upload_local_file_rejects_missing(self, tmp_path):
        from asta.data_analysis import _client
        with pytest.raises(FileNotFoundError):
            _client.upload_local_file("http://dv.local", "tok", str(tmp_path / "nope.csv"))

    def test_upload_local_file_rejects_bad_filename(self, tmp_path):
        from asta.data_analysis import _client
        f = tmp_path / "ok.csv"
        f.write_text("x")
        with pytest.raises(ValueError):
            _client.upload_local_file(
                "http://dv.local", "tok", str(f), filename="../escape.csv"
            )
