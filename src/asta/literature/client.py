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

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config, get_config_path


class AstaPaperFinder:
    """Client for Asta Paper Finder API using headless endpoint"""

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
        include_rejected: str = "none",
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
            "include_rejected": include_rejected,
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
            "rejected": result.get("rejected"),
        }

        # Save to file if path provided
        if save_to_file:
            with open(save_to_file, "w") as f:
                json.dump(search_data, f, indent=2)
            search_data["file_path"] = str(save_to_file)

        return search_data

    def snowball(
        self,
        mode: str,
        seeds: list[dict[str, Any]],
        query: str | None = None,
        forward_top_k: int | None = None,
        backward_top_k: int | None = None,
        snippet_top_k: int | None = None,
        include_full_metadata: bool = True,
        timeout: int = 300,
        save_to_file: Path | None = None,
    ) -> dict[str, Any]:
        """Execute a one-shot citation snowball using the headless endpoint.

        Given seed papers (corpus_id + relevance grade 0-3), promotes candidate
        papers related by citation (backward = references, forward = citations)
        or by snippet citances.

        Args:
            mode: 'backward' (references of the seeds), 'forward' (papers citing
                the seeds), or 'citances' (papers referenced from the seeds'
                snippet citation contexts, reranked against ``query``). All three
                are supported by the mabool headless snowball endpoint.
            seeds: List of {"corpus_id": str, "relevance": int 0-3}.
            query: Search query. REQUIRED when mode == 'citances'.
            forward_top_k: Number of forward-cited candidates to promote.
            backward_top_k: Number of backward-cited candidates to promote.
            snippet_top_k: Number of snippet-derived candidates to promote.
            include_full_metadata: Whether to return full paper details.
            timeout: Maximum time to wait for results (seconds).
            save_to_file: Optional path to save results. If None, no file is saved.

        Returns:
            Search results in the same shape as ``find_papers`` (with a ``widget``
            containing ``results`` and ``response_text``).
        """
        if mode == "citances" and not query:
            raise ValueError("query is required when mode == 'citances'")

        url = f"{self.base_url}/api/3/headless/snowball"

        request_body: dict[str, Any] = {
            "mode": mode,
            "seeds": seeds,
            "include_full_metadata": include_full_metadata,
            "timeout_seconds": timeout,
        }
        # Only send optional fields when provided so the request stays compatible
        # with server versions that don't yet accept them.
        if query is not None:
            request_body["query"] = query
        if forward_top_k is not None:
            request_body["forward_top_k"] = forward_top_k
        if backward_top_k is not None:
            request_body["backward_top_k"] = backward_top_k
        if snippet_top_k is not None:
            request_body["snippet_top_k"] = snippet_top_k

        result = self._request(url, method="POST", data=request_body)

        if "error" in result and result["error"]:
            error = result["error"]
            raise Exception(f"Snowball failed: {error}")

        # HeadlessSearchPaper uses `relevant_snippets`; the Paper model reads
        # snippets from `snippets`. Normalize so result parsing is reused.
        papers = result.get("papers", [])
        for paper in papers:
            if "relevant_snippets" in paper and "snippets" not in paper:
                paper["snippets"] = paper.get("relevant_snippets") or []
            # Paper model requires relevance_score; it's absent unless
            # include_full_metadata=True. Default to 0.0.
            if paper.get("relevance_score") is None:
                paper["relevance_score"] = 0.0

        search_data = {
            "query": query or "",
            "widget": {
                "results": papers,
                "response_text": result.get("response_text", ""),
            },
            "status": "completed",
            "timestamp": time.time(),
            "paper_count": len(papers),
        }

        if save_to_file:
            with open(save_to_file, "w") as f:
                json.dump(search_data, f, indent=2)
            search_data["file_path"] = str(save_to_file)

        return search_data
