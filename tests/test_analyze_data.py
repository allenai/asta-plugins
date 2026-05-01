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
        "asta.analyze_data.upload.get_access_token", lambda: "fake-token"
    )


class TestUpload:
    def test_single_file_emits_structured_json(self, runner, tmp_path):
        f = tmp_path / "titanic.csv"
        f.write_text("a,b\n1,2\n")

        with patch("asta.analyze_data.upload.upload_local_file") as up:
            up.return_value = {
                "s3_uri": f"s3://bucket/userdata/u/context/{CTX}/titanic.csv",
                "filename": "titanic.csv",
                "size": 10,
                "content_type": "text/csv",
            }
            result = runner.invoke(
                cli,
                ["analyze-data", "upload", "--context-id", CTX, str(f)],
            )

        assert result.exit_code == 0, result.output
        up.assert_called_once()
        # Helper should receive the context_id by keyword.
        assert up.call_args.kwargs["context_id"] == CTX

        payload = json.loads(result.stdout)
        assert payload["context_id"] == CTX
        assert payload["datasets"] == [
            {
                "s3_uri": f"s3://bucket/userdata/u/context/{CTX}/titanic.csv",
                "filename": "titanic.csv",
                "size": 10,
                "content_type": "text/csv",
            }
        ]
        # Old <astaattachment> tag should be gone — the structured JSON
        # is now the only contract.
        assert "astaattachment" not in result.output

    def test_multiple_files_preserve_order(self, runner, tmp_path):
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("x")
        b.write_text("y")

        with patch("asta.analyze_data.upload.upload_local_file") as up:
            up.side_effect = [
                {
                    "s3_uri": f"s3://b/u/context/{CTX}/a.csv",
                    "filename": "a.csv",
                    "size": 1,
                    "content_type": "text/csv",
                },
                {
                    "s3_uri": f"s3://b/u/context/{CTX}/b.csv",
                    "filename": "b.csv",
                    "size": 1,
                    "content_type": "text/csv",
                },
            ]
            result = runner.invoke(
                cli,
                ["analyze-data", "upload", "--context-id", CTX, str(a), str(b)],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert [d["s3_uri"] for d in payload["datasets"]] == [
            f"s3://b/u/context/{CTX}/a.csv",
            f"s3://b/u/context/{CTX}/b.csv",
        ]

    def test_requires_context_id(self, runner, tmp_path):
        f = tmp_path / "x.csv"
        f.write_text("x")
        result = runner.invoke(cli, ["analyze-data", "upload", str(f)])
        assert result.exit_code != 0
        assert "context-id" in result.output.lower()

    def test_requires_at_least_one_file(self, runner):
        result = runner.invoke(cli, ["analyze-data", "upload", "--context-id", CTX])
        assert result.exit_code != 0

    def test_missing_file_fails_before_upload(self, runner):
        with patch("asta.analyze_data.upload.upload_local_file") as up:
            result = runner.invoke(
                cli,
                ["analyze-data", "upload", "--context-id", CTX, "/no/such/file.csv"],
            )
        assert result.exit_code != 0
        up.assert_not_called()

    def test_over_5gb_fails_fast(self, runner, tmp_path):
        f = tmp_path / "huge.csv"
        f.write_text("x")

        with patch("asta.analyze_data.upload.upload_local_file") as up:
            up.side_effect = ValueError(
                "File is 6.00 GiB; single-PUT uploads are limited to 5 GiB."
            )
            result = runner.invoke(
                cli,
                ["analyze-data", "upload", "--context-id", CTX, str(f)],
            )

        assert result.exit_code != 0
        assert "5 GiB" in result.output


class TestGroupWiring:
    def test_analyze_data_help_lists_inherited_subcommands(self, runner):
        # `analyze` is gone — the skill orchestrates upload + send-message.
        result = runner.invoke(cli, ["analyze-data", "--help"])
        assert result.exit_code == 0
        for sub in ("card", "send-message", "task", "upload"):
            assert sub in result.output
        assert "analyze " not in result.output  # no bespoke analyze command


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
        from asta.analyze_data import upload as upload_mod

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
            "asta.analyze_data.upload.urllib.request.urlopen",
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
        from asta.analyze_data import upload as upload_mod

        with pytest.raises(FileNotFoundError):
            upload_mod.upload_local_file(
                "http://dv.local", "tok", str(tmp_path / "nope.csv"), context_id=CTX
            )

    def test_upload_local_file_rejects_path_traversal(self, tmp_path):
        from asta.analyze_data import upload as upload_mod

        # The os.path.basename of a traversal-style path on the *server side*
        # is what dv-core enforces, but we still defensively reject `..` in
        # the resolved basename.
        evil = tmp_path / ".."
        with pytest.raises((FileNotFoundError, ValueError)):
            upload_mod.upload_local_file(
                "http://dv.local", "tok", str(evil), context_id=CTX
            )
