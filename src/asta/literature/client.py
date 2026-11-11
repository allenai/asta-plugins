#!/usr/bin/env python3
"""
Asta Paper Finder API Client
"""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from asta.literature.v4_papers import papers_of
from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config, get_config_path
from asta.utils.headers import identity_headers

POLL_INTERVAL_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 60
FINAL_STATUSES = ("completed", "failed")


class PaperFinderAPIError(Exception):
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class AstaPaperFinder:
    """Client for Asta Paper Finder's tasks API (v4)"""

    def __init__(self, base_url: str | None = None, access_token: str | None = None):
        # Load base URL from config if not provided
        if base_url is None:
            try:
                config = get_api_config("paper_finder")
                base_url = config.get("base_url")
            except (KeyError, FileNotFoundError):
                base_url = None

        if not base_url:
            raise ValueError(
                f"No value for apis.paper_finder.base_url in {get_config_path()}"
                "base_url is required. Either provide it as a parameter or configure it in asta.conf"
            )

        # Load access token from storage if not provided
        # AuthenticationError will propagate with helpful message
        if access_token is None:
            access_token = get_access_token()

        self.base_url = base_url
        self.access_token = access_token
        self.headers = {
            **identity_headers(),
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _request(
        self, url: str, method: str = "GET", data: dict | None = None
    ) -> dict[str, Any]:
        """Make an HTTP request and return JSON response"""
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            url, data=body, headers=self.headers, method=method
        )
        try:
            response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS)
            return json.loads(response.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                error_data = json.loads(error_body)
                error_msg = error_data.get("detail", str(e))
            except json.JSONDecodeError:
                error_msg = error_body or str(e)
            retry_after = e.headers.get("Retry-After")
            raise PaperFinderAPIError(
                f"API request failed: {error_msg}",
                retry_after=int(retry_after) if retry_after else None,
            ) from e

    def find_papers(
        self,
        query: str,
        timeout: int = 300,
        save_to_file: Path | None = None,
        operation_mode: str = "infer",
    ) -> dict[str, Any]:
        """Run a one-shot paper search as a Paper Finder v4 task and wait for it.

        Args:
            query: Search query
            timeout: Seconds to wait for the task to finish, polling included
            save_to_file: Optional path to save results. If None, no file is saved.
            operation_mode: Search strategy - 'infer', 'fast', or 'diligent' (default: 'infer')

        Returns:
            Complete search results with papers

        Raises:
            TimeoutError: The task did not finish within ``timeout``.
        """
        deadline = time.monotonic() + timeout
        task_id = self._start_task(
            {
                "query": query,
                "operation_mode": operation_mode,
                "worker_profile": "standard",
                "caller": {"surface": "headless"},
            },
            deadline,
        )
        result = self._await_result(task_id, timeout, deadline)

        if result["status"] == "failed":
            error = result["error"]
            raise Exception(
                f"Paper search failed: {error['message']} ({error['code']})"
            )

        papers = [
            paper.model_dump(mode="json") for paper in papers_of(result["artifacts"])
        ]

        # Build search data in format compatible with existing models
        search_data = {
            "query": query,
            "widget": {
                "results": papers,
                "response_text": result.get("responseText", ""),
            },
            "status": "completed",
            "timestamp": time.time(),
            "paper_count": len(papers),
        }

        # Save to file if path provided
        if save_to_file:
            with open(save_to_file, "w") as f:
                json.dump(search_data, f, indent=2)
            search_data["file_path"] = str(save_to_file)

        return search_data

    def _start_task(self, request_body: dict[str, Any], deadline: float) -> str:
        """POST the task, waiting out ``Retry-After`` while Paper Finder's queue is full."""
        while True:
            try:
                return self._request(
                    f"{self.base_url}/api/4/tasks", method="POST", data=request_body
                )["taskId"]
            except PaperFinderAPIError as e:
                if e.retry_after is None or time.monotonic() + e.retry_after > deadline:
                    raise
                time.sleep(e.retry_after)

    def _await_result(
        self, task_id: str, timeout: int, deadline: float
    ) -> dict[str, Any]:
        # Built from the task id, not the 202's Location header: through the
        # gateway, Location lacks the gateway's /api/paper-finder prefix.
        url = f"{self.base_url}/api/4/tasks/{task_id}/result?preset=full"
        while True:
            result = self._request(url)
            if result["status"] in FINAL_STATUSES:
                return result
            if time.monotonic() + POLL_INTERVAL_SECONDS > deadline:
                raise TimeoutError(
                    f"Paper search task {task_id} did not finish within {timeout}s"
                )
            time.sleep(POLL_INTERVAL_SECONDS)
