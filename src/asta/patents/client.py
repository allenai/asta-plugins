"""S2 public-API patent client.

Patents are served by the same s2-public-api service as papers, under the
``/graph/v1/patent`` path prefix (see allenai/s2-public-api). This client
therefore reuses the ``semantic_scholar`` base URL and auth token rather than
introducing a separate endpoint config.

Endpoints (firs2#150 B4a/B4b):
  - GET /graph/v1/patent/search
  - GET /graph/v1/patent/<ucid>
  - GET /graph/v1/patent/forward-citations/<corpus_id>

The cluster returns 503 until it has been fed (firs2#150 B3); until then these
calls surface that error verbatim.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config, get_config_path


class PatentClient:
    """Client for the S2 public-API patent endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        access_token: str | None = None,
    ):
        # Patents live on the same service as papers (semantic_scholar base URL).
        if base_url is None:
            try:
                config = get_api_config("semantic_scholar")
                base_url = config.get("base_url")
            except (KeyError, FileNotFoundError):
                base_url = None

        if not base_url:
            raise ValueError(
                f"No value for apis.semantic_scholar.base_url in {get_config_path()}"
            )

        # AuthenticationError will propagate with a helpful message.
        if access_token is None:
            access_token = get_access_token()

        self.base_url = base_url
        self.access_token = access_token
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request to the API."""
        url = f"{self.base_url}{path}"
        if params:
            params = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers=self.headers)
        try:
            response = urllib.request.urlopen(req)
            return json.loads(response.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise Exception(f"API error {e.code}: {error_body}")

    def search(
        self,
        query: str,
        fields: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """BM25 lexical search over title/abstract/claims/specification.

        Args:
            query: Search query.
            fields: Comma-separated patent fields to return (``ucid`` is always
                included by the API).
            limit: Max results (default 10, max 100).
            offset: Starting position of the batch (default 0).
        """
        params = {
            "query": query,
            "fields": fields,
            "limit": min(limit, 100),
            "offset": offset,
        }
        return self._request("/graph/v1/patent/search", params)

    def get_patent(self, ucid: str, fields: str | None = None) -> dict[str, Any]:
        """Get detail metadata for a single patent by its UCID.

        Args:
            ucid: Unified Citation Identifier, e.g. ``US-10123456-B2``.
            fields: Comma-separated patent fields to return. The detail endpoint
                can return ``claims`` and ``specification``, which search omits.
        """
        params = {"fields": fields} if fields else None
        ucid_quoted = urllib.parse.quote(ucid, safe="")
        return self._request(f"/graph/v1/patent/{ucid_quoted}", params)

    def forward_citations(
        self,
        corpus_id: int,
        fields: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Patents that cite a given paper (corpus_id -> patents).

        Args:
            corpus_id: S2 corpusId of the paper.
            fields: Comma-separated patent fields to return.
            limit: Max results (default 10, max 100).
            offset: Starting position of the batch (default 0).
        """
        params = {
            "fields": fields,
            "limit": min(limit, 100),
            "offset": offset,
        }
        return self._request(
            f"/graph/v1/patent/forward-citations/{int(corpus_id)}", params
        )
