"""Nora Report Generation API client"""

import json
import urllib.error
import urllib.request
from typing import Any

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config, get_config_path


class NoraReportClient:
    """Client for the Nora report generation API."""

    def __init__(self, base_url: str | None = None, access_token: str | None = None):
        if base_url is None:
            try:
                config = get_api_config("report")
                base_url = config.get("base_url")
            except (KeyError, FileNotFoundError):
                base_url = None

        if not base_url:
            raise ValueError(
                f"No value for apis.report.base_url in {get_config_path()}. "
                "base_url is required. Either provide it as a parameter or configure it in asta.conf"
            )

        if access_token is None:
            access_token = get_access_token()

        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _request(self, data: dict) -> dict[str, Any]:
        """POST to the generate-report endpoint and return parsed JSON."""
        url = f"{self.base_url}/generate-report"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                error_msg = json.loads(error_body).get("detail", str(e))
            except json.JSONDecodeError:
                error_msg = error_body or str(e)
            raise Exception(f"API request failed ({e.code}): {error_msg}") from e

    def generate_report(
        self,
        documents: list[dict],
        query: str = "",
    ) -> dict[str, Any]:
        """Generate a literature report from pre-retrieved documents.

        Args:
            documents: List of document dicts matching the GenerateReportRequest
                Document schema (corpus_id, title, abstract, authors, snippets,
                and optional metadata fields).
            query: The research question / topic for the report.

        Returns:
            A TaskResult dict with report_title, sections, report_id, event_id,
            and cost.

        Raises:
            Exception: On API errors.
        """
        payload = {
            "query": query,
            "documents": documents,
            "truncated_result": False,
        }

        return self._request(payload)
