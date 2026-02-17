#!/usr/bin/env python3
"""
Asta Paper Finder API Client
"""

import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class AstaPaperFinder:
    """Client for Asta Paper Finder API"""

    def __init__(self, base_url: str = "https://asta.allen.ai"):
        self.base_url = base_url
        self.mabool_url = "https://mabool-demo.allen.ai"
        self.user_id = str(uuid.uuid4())
        self.headers = {
            "X-Anonymous-User-ID": self.user_id,
            "Content-Type": "application/json",
        }

    def _request(
        self, url: str, method: str = "GET", data: dict | None = None
    ) -> dict[str, Any] | list:
        """Make an HTTP request and return JSON response"""
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            url, data=body, headers=self.headers, method=method
        )
        response = urllib.request.urlopen(req)
        return json.loads(response.read())

    def create_thread(self) -> str:
        """Create a new thread"""
        result = self._request(f"{self.base_url}/api/chat/thread", method="PUT")
        return result["thread"]["key"]

    def send_message(
        self, text: str, thread_id: str, profile: str = "paper-finder-only"
    ) -> dict[str, Any]:
        """Send a message to the thread"""
        return self._request(
            f"{self.base_url}/api/chat/message",
            method="POST",
            data={"text": text, "thread_id": thread_id, "profile": profile},
        )

    def get_widget_id(self, thread_id: str, max_retries: int = 20) -> str | None:
        """Get the widget ID from thread events"""
        url = f"{self.base_url}/api/rest/thread/{thread_id}/event/widget_paper_finder"
        for _ in range(max_retries):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                response = urllib.request.urlopen(req)
                data = json.loads(response.read())
                last_event = data.get("last_event")
                if last_event and isinstance(last_event, dict):
                    event_data = last_event.get("data")
                    if event_data and isinstance(event_data, dict):
                        widget_id = event_data.get("id")
                        if widget_id:
                            return widget_id
            except urllib.error.HTTPError:
                pass
            time.sleep(2)
        return None

    def get_widget_results(self, widget_id: str) -> dict[str, Any] | list:
        """Get widget results from mabool service"""
        url = f"{self.mabool_url}/api/2/rounds/{widget_id}/result/widget"
        req = urllib.request.Request(url, headers=self.headers)
        response = urllib.request.urlopen(req)
        return json.loads(response.read())

    def poll_for_results(self, widget_id: str, timeout: int = 300):
        """Poll for results until completion or timeout"""
        start_time = time.time()
        poll_interval = 2

        while time.time() - start_time < timeout:
            try:
                result = self.get_widget_results(widget_id)

                # Handle if result is a list - got the papers directly
                if isinstance(result, list):
                    return {
                        "roundStatus": {"kind": "completed"},
                        "results": result,
                        "thread_id": None,
                        "widget_id": widget_id,
                    }

                # Handle dict response with roundStatus
                status = result.get("roundStatus", {}).get("kind", "unknown")

                if status == "completed":
                    return result
                elif status == "failed":
                    error = result.get("roundStatus", {}).get("error", "Unknown error")
                    raise Exception(f"Paper finder failed: {error}")

            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise

            time.sleep(poll_interval)

        raise TimeoutError(f"Timeout after {timeout} seconds")

    def start_search(self, query: str) -> str:
        """Start a paper search and return thread_id immediately (non-blocking)"""
        thread_id = self.create_thread()
        self.send_message(query, thread_id)
        return thread_id

    def find_papers(
        self, query: str, timeout: int = 300, save_to_file: Path | None = None
    ) -> dict[str, Any]:
        """Complete workflow to find papers (blocking).

        Args:
            query: Search query
            timeout: Maximum time to wait for results
            save_to_file: Optional path to save results. If None, no file is saved.

        Returns:
            Complete search results including widget data
        """
        thread_id = self.start_search(query)

        # Get widget ID
        widget_id = self.get_widget_id(thread_id)
        if not widget_id:
            raise Exception("Failed to get widget ID after retries")

        # Poll for results
        widget_result = self.poll_for_results(widget_id, timeout)

        papers = widget_result.get("results", [])

        # Build complete search data
        search_data = {
            "query": query,
            "thread_id": thread_id,
            "widget_id": widget_id,
            "status": "completed",
            "widget": widget_result,
            "timestamp": time.time(),
            "paper_count": len(papers),
        }

        # Save to file if path provided
        if save_to_file:
            with open(save_to_file, "w") as f:
                json.dump(search_data, f, indent=2)
            search_data["file_path"] = str(save_to_file)

        return search_data
