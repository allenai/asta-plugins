#!/usr/bin/env python3
"""
Asta Paper Finder API Client
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class AstaPaperFinder:
    """Client for Asta Paper Finder API"""

    def __init__(
        self,
        base_url: str | None = None,
        mabool_url: str | None = None,
        user_id: str | None = None,
    ):
        self.base_url = base_url or os.environ.get(
            "ASTA_API_URL", "REDACTED_ASTA_PROD_URL"
        )
        self.mabool_url = mabool_url or os.environ.get(
            "ASTA_MABOOL_URL", "REDACTED_MABOOL_WORKERS_URL"
        )
        self.user_id = user_id or str(uuid.uuid4())
        self.headers = {
            "X-Anonymous-User-ID": self.user_id,
            "Content-Type": "application/json",
        }

    # -- private helpers --

    def _request(
        self, url: str, method: str = "GET", data: dict | None = None
    ) -> dict[str, Any] | list:
        """Make an HTTP request and return JSON response."""
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            url, data=body, headers=self.headers, method=method
        )
        response = urllib.request.urlopen(req)
        return json.loads(response.read())

    def _get_current_widget_id(self, thread_id: str) -> str | None:
        """Fetch the current widget ID (single request, no polling)."""
        url = f"{self.base_url}/api/rest/thread/{thread_id}/event/widget_paper_finder"
        try:
            req = urllib.request.Request(url, headers=self.headers)
            response = urllib.request.urlopen(req)
            data = json.loads(response.read())
            last_event = data.get("last_event")
            if last_event and isinstance(last_event, dict):
                event_data = last_event.get("data")
                if event_data and isinstance(event_data, dict):
                    return event_data.get("id")
        except urllib.error.HTTPError:
            pass
        return None

    def _get_agent_messages(self, thread_id: str) -> list[dict]:
        """Return all agent messages from a thread (in order)."""
        data = self.get_thread(thread_id)
        messages = data.get("thread", {}).get("messages", [])
        return [
            m for m in messages if m.get("sender", {}).get("display_name") == "asta"
        ]

    def _fetch_widget(
        self,
        widget_id: str | None,
        timeout: int,
    ) -> tuple[dict, list]:
        """Fetch widget results if a widget ID is available."""
        if not widget_id:
            return {}, []
        result = self.poll_for_results(widget_id, timeout)
        return result, result.get("results", [])

    # -- low-level API --

    def create_thread(self) -> str:
        """Create a new thread."""
        result = self._request(f"{self.base_url}/api/chat/thread", method="PUT")
        return result["thread"]["key"]

    def send_message(
        self, text: str, thread_id: str, profile: str = "paper-finder-workers"
    ) -> dict[str, Any]:
        """Send a message to the thread."""
        return self._request(
            f"{self.base_url}/api/chat/message",
            method="POST",
            data={"text": text, "thread_id": thread_id, "profile": profile},
        )

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        """Fetch the full thread including messages."""
        return self._request(f"{self.base_url}/api/chat/thread/{thread_id}")

    def get_widget_results(self, widget_id: str) -> dict[str, Any] | list:
        """Get widget results from mabool service."""
        url = f"{self.mabool_url}/api/2/rounds/{widget_id}/result/widget"
        req = urllib.request.Request(url, headers=self.headers)
        response = urllib.request.urlopen(req)
        return json.loads(response.read())

    # -- polling --

    def poll_for_results(self, widget_id: str, timeout: int = 300):
        """Poll for widget results until completion or timeout."""
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

    def poll_for_agent_response(
        self,
        thread_id: str,
        *,
        previous_message_count: int,
        timeout: int = 300,
        interval: int = 5,
    ) -> str:
        """Poll until the agent posts a new message in the thread.

        Compares the current number of agent messages against
        *previous_message_count* to detect when the agent has responded.
        Returns the new message text, or raises TimeoutError.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                agent_msgs = self._get_agent_messages(thread_id)
                if len(agent_msgs) > previous_message_count:
                    return agent_msgs[-1].get("stripped_text", "")
            except urllib.error.HTTPError:
                pass
            time.sleep(interval)
        raise TimeoutError(f"Agent did not respond within {timeout}s")

    # -- high-level workflows --

    def start_search(self, query: str) -> str:
        """Start a paper search and return thread_id immediately (non-blocking)."""
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

        # Wait for the agent to respond (new thread, so 0 previous messages)
        response_text = self.poll_for_agent_response(
            thread_id,
            previous_message_count=0,
            timeout=timeout,
        )

        # By the time the agent responds, the widget is available (if any)
        widget_id = self._get_current_widget_id(thread_id)
        widget_result, papers = self._fetch_widget(widget_id, timeout)

        # Build complete search data
        search_data = {
            "query": query,
            "thread_id": thread_id,
            "widget_id": widget_id,
            "status": "completed",
            "response": response_text,
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

    def send_followup(
        self, thread_id: str, message: str, timeout: int = 300
    ) -> dict[str, Any]:
        """Send a follow-up message and wait for the agent to respond.

        The agent may respond with text only, or text plus a new paper search.
        We poll for the agent's text response first (always expected), then
        check whether a new widget (paper search) was also produced.
        """
        old_widget_id = self._get_current_widget_id(thread_id)
        prev_agent_count = len(self._get_agent_messages(thread_id))

        self.send_message(message, thread_id)

        # Wait for the agent to respond (text is always expected)
        response_text = self.poll_for_agent_response(
            thread_id,
            previous_message_count=prev_agent_count,
            timeout=timeout,
        )

        # Check once if a new widget was produced — by the time the agent
        # message appears, the widget ID (if any) is already available.
        widget_id = self._get_current_widget_id(thread_id)
        if widget_id == old_widget_id:
            widget_id = None

        widget_result, papers = self._fetch_widget(widget_id, timeout)

        return {
            "thread_id": thread_id,
            "widget_id": widget_id or old_widget_id,
            "response": response_text,
            "widget": widget_result,
            "paper_count": len(papers),
        }
