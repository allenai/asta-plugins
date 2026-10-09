"""Tests for AutoDiscoveryClient.upload_file against the upload-url response shapes."""

import base64
import json
import urllib.error

import pytest

from asta.autodiscovery import client as client_mod
from asta.autodiscovery.client import AutoDiscoveryClient

BASE = "https://gateway.example/api/autodiscovery"


def _token(sub: str = "user-1") -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode()
    return f"h.{payload.rstrip('=')}.s"


class _Resp:
    def __init__(self, body: bytes = b"{}"):
        self.body = body

    def read(self):
        return self.body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Answer generate-upload-url with ``sent.url_info``; record the upload request."""

    class Sent:
        url_info: dict = {}
        upload = None

    def fake_urlopen(req, timeout=None):
        if req.full_url.endswith("/generate-upload-url"):
            return _Resp(json.dumps(Sent.url_info).encode())
        Sent.upload = req
        return _Resp()

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_urlopen)
    return Sent


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "data.csv"
    path.write_bytes(b"a,b\n1,2\n")
    return path


def _client() -> AutoDiscoveryClient:
    return AutoDiscoveryClient(base_url=BASE, access_token=_token())


class TestUploadFile:
    def test_presigned_put_sends_the_raw_file_without_the_token(self, sent, dataset):
        sent.url_info = {
            "upload_url": "https://storage.googleapis.com/bucket/data.csv?X-Goog-Signature=x",
            "upload_method": "PUT",
            "upload_fields": None,
            "storage_path": "gs://bucket/users/u/jobs/r/data/data.csv",
            "filename": "data.csv",
            "expires_at_unix": 0,
        }

        result = _client().upload_file("run-1", str(dataset))

        req = sent.upload
        assert req.get_method() == "PUT"
        assert req.full_url == sent.url_info["upload_url"]
        assert req.data == b"a,b\n1,2\n"
        assert req.get_header("Content-type") == "text/csv"
        assert req.get_header("Authorization") is None
        assert result == {
            "filename": "data.csv",
            "storage_path": "gs://bucket/users/u/jobs/r/data/data.csv",
            "file_size_bytes": 8,
            "content_type": "text/csv",
        }

    def test_older_response_with_gcs_path_still_works(self, sent, dataset):
        sent.url_info = {
            "upload_url": "https://storage.googleapis.com/bucket/data.csv?sig=x",
            "gcs_path": "gs://bucket/old/data.csv",
            "filename": "data.csv",
            "expires_at_unix": 0,
        }

        result = _client().upload_file("run-1", str(dataset))

        assert sent.upload.get_method() == "PUT"
        assert result["storage_path"] == "gs://bucket/old/data.csv"

    def test_upload_fields_send_a_multipart_form(self, sent, dataset):
        sent.url_info = {
            "upload_url": "https://storage.googleapis.com/bucket",
            "upload_method": "POST",
            "upload_fields": {"key": "users/u/data.csv", "policy": "p"},
            "storage_path": "gs://bucket/users/u/data.csv",
            "filename": "data.csv",
            "expires_at_unix": 0,
        }

        _client().upload_file("run-1", str(dataset))

        req = sent.upload
        assert req.get_method() == "POST"
        form_type = req.get_header("Content-type")
        assert form_type.startswith("multipart/form-data; boundary=")
        boundary = form_type.split("boundary=", 1)[1]
        body = req.data.decode()
        assert body.startswith(f"--{boundary}\r\n")
        assert body.endswith(f"\r\n--{boundary}--\r\n")
        assert 'name="key"\r\n\r\nusers/u/data.csv\r\n' in body
        assert 'name="policy"\r\n\r\np\r\n' in body
        assert (
            'name="file"; filename="data.csv"\r\nContent-Type: text/csv\r\n\r\na,b\n1,2\n'
            in body
        )
        assert req.get_header("Authorization") is None

    def test_the_api_own_endpoint_gets_the_token(self, sent, dataset):
        sent.url_info = {
            "upload_url": "/api/autodiscovery/api/runs/upload",
            "upload_method": "POST",
            "upload_fields": {"runid": "run-1"},
            "storage_path": "file:///data/u/run-1/data.csv",
            "filename": "data.csv",
            "expires_at_unix": 0,
        }

        _client().upload_file("run-1", str(dataset))

        req = sent.upload
        assert (
            req.full_url == "https://gateway.example/api/autodiscovery/api/runs/upload"
        )
        assert req.get_header("Authorization") == f"Bearer {_token()}"
        assert req.get_header("Content-type").startswith("multipart/form-data")

    def test_a_failed_upload_reports_the_status_and_body(
        self, sent, dataset, monkeypatch
    ):
        sent.url_info = {
            "upload_url": "https://storage.googleapis.com/bucket/data.csv?sig=x",
            "storage_path": "gs://bucket/data.csv",
            "filename": "data.csv",
            "expires_at_unix": 0,
        }
        original = client_mod.urllib.request.urlopen

        def failing(req, timeout=None):
            if req.full_url.startswith("https://storage.googleapis.com"):
                raise urllib.error.HTTPError(
                    req.full_url, 403, "Forbidden", {}, _Resp(b"SignatureDoesNotMatch")
                )
            return original(req, timeout)

        monkeypatch.setattr(client_mod.urllib.request, "urlopen", failing)

        with pytest.raises(Exception, match="Upload error 403: SignatureDoesNotMatch"):
            _client().upload_file("run-1", str(dataset))
