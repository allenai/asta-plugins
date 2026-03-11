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


class AstaPaperFinder:
    """Client for Asta Paper Finder API using async headless endpoint"""

    def __init__(self, base_url: str = "REDACTED_MABOOL_WORKERS_URL"):
        self.base_url = base_url
        self.headers = {
            "Content-Type": "application/json",
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
            response = urllib.request.urlopen(req)
            return json.loads(response.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                error_data = json.loads(error_body)
                error_msg = error_data.get("detail", str(e))
            except json.JSONDecodeError:
                error_msg = error_body or str(e)
            raise Exception(f"API request failed: {error_msg}") from e

    def start_search(
        self,
        query: str,
        operation_mode: str = "infer",
        include_full_metadata: bool = True,
        timeout_seconds: int = 300,
    ) -> str:
        """Start a paper search and return task_id immediately.

        Args:
            query: Search query
            operation_mode: Search strategy - 'infer', 'fast', or 'diligent'
            include_full_metadata: Whether to return full paper details
            timeout_seconds: Server-side timeout for the search

        Returns:
            task_id for polling results
        """
        url = f"{self.base_url}/api/3/headless/paper-search"

        request_body = {
            "query": query,
            "operation_mode": operation_mode,
            "include_full_metadata": include_full_metadata,
            "timeout_seconds": timeout_seconds,
        }

        result = self._request(url, method="POST", data=request_body)
        task_id = result.get("task_id")

        if not task_id:
            raise Exception("API did not return task_id")

        return task_id

    def poll_for_results(
        self, task_id: str, timeout: int = 300, poll_interval: int = 2
    ) -> dict[str, Any]:
        """Poll for search results until completed, failed, or timeout.

        Args:
            task_id: Task ID from start_search()
            timeout: Maximum time to wait for results (seconds)
            poll_interval: Time between polling requests (seconds)

        Returns:
            Search results response

        Raises:
            TimeoutError: If timeout is exceeded
            Exception: If search fails
        """
        url = f"{self.base_url}/api/3/headless/paper-search/{task_id}"
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                result = self._request(url, method="GET")
                status = result.get("status")

                if status == "completed":
                    return result
                elif status == "failed":
                    error = result.get("error", {})
                    error_msg = error.get("message", "Unknown error")
                    raise Exception(f"Paper search failed: {error_msg}")
                elif status == "pending":
                    # Continue polling
                    time.sleep(poll_interval)
                else:
                    raise Exception(f"Unknown status: {status}")

            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise Exception(f"Task {task_id} not found")
                raise

        raise TimeoutError(f"Search timed out after {timeout} seconds")

    def find_papers(
        self,
        query: str,
        timeout: int = 300,
        save_to_file: Path | None = None,
        operation_mode: str = "infer",
        include_full_metadata: bool = True,
    ) -> dict[str, Any]:
        """Execute a paper search using the async headless endpoint.

        Args:
            query: Search query
            timeout: Maximum time to wait for results (seconds)
            save_to_file: Optional path to save results. If None, no file is saved.
            operation_mode: Search strategy - 'infer', 'fast', or 'diligent' (default: 'infer')
            include_full_metadata: Whether to return full paper details (default: True)

        Returns:
            Complete search results with papers
        """
        # Start the search (non-blocking, returns task_id)
        task_id = self.start_search(
            query=query,
            operation_mode=operation_mode,
            include_full_metadata=include_full_metadata,
            timeout_seconds=timeout,
        )

        # Poll for results
        result = self.poll_for_results(task_id, timeout=timeout)

        # Check for errors in result
        if "error" in result and result["error"]:
            error = result["error"]
            raise Exception(f"Paper search failed: {error}")

        # Get papers (Pydantic models will handle snake_case -> camelCase conversion)
        papers = result.get("papers", [])

        # Build search data in format compatible with existing models
        search_data = {
            "query": query,
            "task_id": task_id,
            "widget": {
                "results": papers,
                "response_text": result.get("response_text", ""),
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
