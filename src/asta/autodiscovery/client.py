"""AutoDiscovery API client (stdlib only)."""

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from typing import Any

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config, get_config_path


class AutoDiscoveryClient:
    """Client for the AutoDiscovery API at autodiscovery.allen.ai."""

    def __init__(
        self,
        base_url: str | None = None,
        access_token: str | None = None,
    ):
        if base_url is None:
            try:
                base_url = get_api_config("autodiscovery").get("base_url")
            except (KeyError, FileNotFoundError):
                base_url = None
        if not base_url:
            raise ValueError(
                f"No value for apis.autodiscovery.base_url in {get_config_path()}"
            )

        if access_token is None:
            access_token = get_access_token()

        self.base_url = base_url
        self.access_token = access_token
        self.user_id = self._extract_user_id()
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    def _extract_user_id(self) -> str:
        """Extract user ID (sub claim) from the access token JWT."""
        parts = self.access_token.split(".")
        if len(parts) >= 2:
            payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            if "sub" in claims:
                return claims["sub"]
        raise ValueError("Cannot extract user ID from access token")

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise Exception(f"API error {e.code}: {error_body}")

    def _post(self, path: str, body: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(body or {}).encode()
        headers = {**self.headers, "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise Exception(f"API error {e.code}: {error_body}")

    def list_runs(self) -> dict[str, Any]:
        return self._get(f"/api/runs/{self.user_id}/list")

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._get(f"/api/runs/{self.user_id}/{run_id}")

    def get_status(self, run_id: str) -> dict[str, Any]:
        return self._get(f"/api/runs/{self.user_id}/{run_id}/status")

    def list_experiments(self, run_id: str) -> dict[str, Any]:
        return self._post(f"/api/runs/{self.user_id}/{run_id}/experiments", {})

    def get_experiment(self, run_id: str, experiment_id: str) -> dict[str, Any]:
        return self._get(
            f"/api/runs/{self.user_id}/{run_id}/experiments/{experiment_id}"
        )

    def create_run(self) -> dict[str, Any]:
        return self._post("/api/runs/create")

    def save_metadata(self, run_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return self._post(f"/api/runs/{run_id}/metadata", {"metadata": metadata})

    def get_metadata(self, run_id: str) -> dict[str, Any]:
        return self._get(f"/api/runs/{self.user_id}/{run_id}/metadata")

    def generate_upload_url(
        self,
        run_id: str,
        filename: str,
        content_type: str,
        file_size_bytes: int,
    ) -> dict[str, Any]:
        return self._post(
            f"/api/runs/{run_id}/generate-upload-url",
            {
                "filename": filename,
                "content_type": content_type,
                "file_size_bytes": file_size_bytes,
            },
        )

    def upload_file(self, run_id: str, filepath: str) -> dict[str, Any]:
        """Upload a local file to a run via presigned URL."""
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"

        url_info = self.generate_upload_url(run_id, filename, content_type, file_size)

        with open(filepath, "rb") as f:
            data = f.read()
        req = urllib.request.Request(
            url_info["upload_url"],
            data=data,
            method="PUT",
            headers={"Content-Type": content_type},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            resp.read()

        return {
            "filename": filename,
            "gcs_path": url_info["gcs_path"],
            "file_size_bytes": file_size,
            "content_type": content_type,
        }

    def submit_run(self, run_id: str) -> dict[str, Any]:
        return self._post("/api/runs/submit", {"runid": run_id})

    def fork_run(self, parent_run_id: str) -> dict[str, Any]:
        return self._post("/api/runs/fork", {"parent_run_id": parent_run_id})

    def get_credits(self) -> dict[str, Any]:
        return self._get("/api/user/me/credits")
