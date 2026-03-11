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
    """Client for Asta Paper Finder API using headless endpoint"""

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

    def find_papers(
        self,
        query: str,
        timeout: int = 300,
        save_to_file: Path | None = None,
        operation_mode: str = "infer",
        include_full_metadata: bool = True,
    ) -> dict[str, Any]:
        """Execute a one-shot paper search using the headless endpoint.

        Args:
            query: Search query
            timeout: Maximum time to wait for results (seconds)
            save_to_file: Optional path to save results. If None, no file is saved.
            operation_mode: Search strategy - 'infer', 'fast', or 'diligent' (default: 'infer')
            include_full_metadata: Whether to return full paper details (default: True)

        Returns:
            Complete search results with papers
        """
        url = f"{self.base_url}/api/3/headless/paper-search"

        request_body = {
            "query": query,
            "operation_mode": operation_mode,
            "include_full_metadata": include_full_metadata,
            "timeout_seconds": timeout,
        }

        # Make the synchronous request
        result = self._request(url, method="POST", data=request_body)

        # Check for errors
        if "error" in result and result["error"]:
            error = result["error"]
            raise Exception(f"Paper search failed: {error}")

        papers = result.get("papers", [])

        # Build search data in format compatible with existing models
        search_data = {
            "query": query,
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
