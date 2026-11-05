"""Tests for the `asta feedback` plugin."""

import gzip
import io
import json
import tarfile
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli

SUBMISSION_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def _stub_auth(monkeypatch):
    monkeypatch.setattr("asta.feedback.submit.get_access_token", lambda: "fake-token")


def _make_submission(tmp_path, narrative="It works great.\n", attachments=None):
    """Populate a submission directory; return its path."""
    d = tmp_path / "my-project"
    d.mkdir()
    (d / "FEEDBACK.md").write_text(narrative)
    for name, content in (attachments or {}).items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def _extract(data: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}


def _stub_submission_response() -> dict:
    return {
        "submission_id": SUBMISSION_ID,
        "upload_url": "https://storage.googleapis.com/bucket/feedback?sig=abc",
        "gcs_uri": f"gs://bucket/feedback/{SUBMISSION_ID}/my-project.tar.gz",
        "expires_in": 3600,
    }


class TestBundle:
    def test_bundle_includes_manifest_and_files(self, tmp_path):
        from asta.feedback._bundle import build_bundle

        d = _make_submission(
            tmp_path,
            attachments={"report.html": "<h1>hi</h1>", "notes/summary.md": "# s"},
        )
        bundle = build_bundle(d)

        assert bundle.num_files == 3
        members = _extract(bundle.data)
        assert set(members) == {
            "manifest.json",
            "FEEDBACK.md",
            "report.html",
            "notes/summary.md",
        }

        manifest = json.loads(members["manifest.json"])
        assert manifest["narrative"] == "FEEDBACK.md"
        paths = {f["path"] for f in manifest["files"]}
        assert paths == {"FEEDBACK.md", "report.html", "notes/summary.md"}
        md = next(f for f in manifest["files"] if f["path"] == "FEEDBACK.md")
        assert md["content_type"] == "text/markdown"
        assert manifest["client"]["tool"] == "asta-cli"

    def test_bundle_is_deterministic(self, tmp_path):
        from asta.feedback._bundle import build_bundle

        d = _make_submission(tmp_path, attachments={"a.txt": "x"})
        assert build_bundle(d).data == build_bundle(d).data

    def test_bundle_gzip_header_has_no_timestamp(self, tmp_path):
        from asta.feedback._bundle import build_bundle

        d = _make_submission(tmp_path)
        # Bytes 4-8 of the gzip header are the mtime; we zero it.
        header_mtime = build_bundle(d).data[4:8]
        assert header_mtime == b"\x00\x00\x00\x00"

    def test_missing_narrative_raises(self, tmp_path):
        from asta.feedback._bundle import build_bundle

        d = tmp_path / "empty"
        d.mkdir()
        (d / "report.html").write_text("no narrative here")
        with pytest.raises(FileNotFoundError, match="FEEDBACK.md"):
            build_bundle(d)

    def test_hidden_and_cruft_files_excluded(self, tmp_path):
        from asta.feedback._bundle import build_bundle

        d = _make_submission(tmp_path, attachments={"keep.txt": "y"})
        (d / ".DS_Store").write_text("junk")
        (d / ".hidden").write_text("secret")
        (d / ".git").mkdir()
        (d / ".git" / "config").write_text("[core]")

        members = _extract(build_bundle(d).data)
        assert ".DS_Store" not in members
        assert ".hidden" not in members
        assert not any(m.startswith(".git") for m in members)
        assert "keep.txt" in members

    def test_per_file_size_gate(self, tmp_path, monkeypatch):
        from asta.feedback._bundle import build_bundle

        monkeypatch.setenv("ASTA_FEEDBACK_MAX_FILE_MB", "0.001")  # ~1 KiB
        d = _make_submission(tmp_path, attachments={"big.txt": "x" * 5000})
        with pytest.raises(ValueError, match="per-file limit"):
            build_bundle(d)

    def test_total_size_gate(self, tmp_path, monkeypatch):
        from asta.feedback._bundle import build_bundle

        # ~1 KiB total budget; each file under the 1 MiB per-file cap.
        monkeypatch.setenv("ASTA_FEEDBACK_MAX_FILE_MB", "1")
        monkeypatch.setenv("ASTA_FEEDBACK_MAX_TOTAL_MB", "0.001")
        d = _make_submission(
            tmp_path, attachments={"a.txt": "x" * 800, "b.txt": "y" * 800}
        )
        with pytest.raises(ValueError, match="total limit"):
            build_bundle(d)


class TestSubmitCommand:
    def test_submit_mints_then_uploads(self, runner, tmp_path):
        d = _make_submission(tmp_path, attachments={"report.html": "<p>x</p>"})

        with (
            patch("asta.feedback.submit.create_submission") as create,
            patch("asta.feedback.submit.upload_bundle") as upload,
            patch("asta.feedback.submit.feedback_url", return_value="http://fb.local"),
        ):
            create.return_value = _stub_submission_response()
            result = runner.invoke(cli, ["feedback", "submit", str(d)])

        assert result.exit_code == 0, result.output
        assert SUBMISSION_ID in result.output

        create.assert_called_once()
        assert create.call_args.args[0] == "http://fb.local"
        assert create.call_args.args[1] == "fake-token"
        # slug is the submission directory name; filename is a stable constant.
        assert create.call_args.kwargs["slug"] == "my-project"
        assert create.call_args.kwargs["filename"] == "bundle.tar.gz"
        assert create.call_args.kwargs["num_files"] == 2

        # The bytes minted for and the bytes uploaded are the same bundle.
        upload.assert_called_once()
        uploaded_bytes = upload.call_args.args[1]
        assert upload.call_args.args[0] == _stub_submission_response()["upload_url"]
        assert isinstance(uploaded_bytes, bytes) and uploaded_bytes
        assert create.call_args.kwargs["size_bytes"] == len(uploaded_bytes)

    def test_dry_run_skips_network(self, runner, tmp_path):
        d = _make_submission(tmp_path)

        with (
            patch("asta.feedback.submit.create_submission") as create,
            patch("asta.feedback.submit.upload_bundle") as upload,
        ):
            result = runner.invoke(cli, ["feedback", "submit", "--dry-run", str(d)])

        assert result.exit_code == 0, result.output
        create.assert_not_called()
        upload.assert_not_called()
        manifest = json.loads(result.stdout)
        assert manifest["narrative"] == "FEEDBACK.md"

    def test_missing_narrative_fails_before_network(self, runner, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "notes.txt").write_text("no narrative")

        with (
            patch("asta.feedback.submit.create_submission") as create,
            patch("asta.feedback.submit.upload_bundle") as upload,
        ):
            result = runner.invoke(cli, ["feedback", "submit", str(d)])

        assert result.exit_code != 0
        assert "FEEDBACK.md" in result.output
        create.assert_not_called()
        upload.assert_not_called()

    def test_nonexistent_directory_rejected(self, runner):
        result = runner.invoke(cli, ["feedback", "submit", "/no/such/dir"])
        assert result.exit_code != 0


class TestClient:
    def test_create_submission_posts_json_with_bearer(self):
        from asta.feedback import _client

        resp_body = json.dumps(_stub_submission_response()).encode()
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "headers": dict(req.headers),
                    "body": req.data,
                }
            )
            resp = MagicMock()
            resp.read.return_value = resp_body
            resp.__enter__ = lambda self: self
            resp.__exit__ = lambda self, *a: None
            return resp

        with patch(
            "asta.feedback._client.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            out = _client.create_submission(
                "http://fb.local",
                "tok",
                slug="my-project",
                filename="bundle.tar.gz",
                size_bytes=1234,
                num_files=2,
            )

        assert out["submission_id"] == SUBMISSION_ID
        call = calls[0]
        assert call["method"] == "POST"
        assert call["url"] == "http://fb.local/submissions"
        assert call["headers"].get("Authorization") == "Bearer tok"
        body = json.loads(call["body"])
        assert body["slug"] == "my-project"
        assert body["content_type"] == "application/gzip"
        assert body["num_files"] == 2

    def test_create_submission_requires_upload_url(self):
        from asta.feedback import _client

        resp_body = json.dumps({"submission_id": SUBMISSION_ID}).encode()

        def fake_urlopen(req, timeout=None):
            resp = MagicMock()
            resp.read.return_value = resp_body
            resp.__enter__ = lambda self: self
            resp.__exit__ = lambda self, *a: None
            return resp

        with patch(
            "asta.feedback._client.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            with pytest.raises(ValueError, match="upload_url"):
                _client.create_submission(
                    "http://fb.local",
                    "tok",
                    slug="x",
                    filename="bundle.tar.gz",
                    size_bytes=1,
                    num_files=1,
                )

    def test_upload_bundle_puts_bytes_with_content_range(self):
        from asta.feedback import _client

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "headers": dict(req.headers),
                    "body": req.data,
                }
            )
            resp = MagicMock()
            resp.read.return_value = b""
            resp.__enter__ = lambda self: self
            resp.__exit__ = lambda self, *a: None
            return resp

        with patch(
            "asta.feedback._client.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            _client.upload_bundle("https://gcs.example/session?upload_id=1", b"payload")

        call = calls[0]
        assert call["method"] == "PUT"
        assert call["url"] == "https://gcs.example/session?upload_id=1"
        # Resumable single-shot upload: full-range Content-Range, no Content-Type
        # (the object's type was fixed when the session was initiated).
        assert call["headers"].get("Content-range") == "bytes 0-6/7"
        assert call["body"] == b"payload"

    def test_upload_bundle_rejects_empty(self):
        from asta.feedback import _client

        with pytest.raises(ValueError, match="empty"):
            _client.upload_bundle("https://gcs.example/session", b"")


class TestWiring:
    def test_feedback_help_lists_submit(self, runner):
        result = runner.invoke(cli, ["feedback", "--help"])
        assert result.exit_code == 0
        assert "submit" in result.output

    def test_api_config_resolves_base_url(self):
        from asta.utils.config import get_api_config

        cfg = get_api_config("feedback")
        assert cfg["base_url"].endswith("/api/feedback") or cfg["base_url"].startswith(
            "http"
        )


def test_gzip_import_available():
    # Guard: the bundle relies on stdlib gzip/tarfile only.
    assert gzip and tarfile
