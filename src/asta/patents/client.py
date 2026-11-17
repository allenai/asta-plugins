"""s2 public api patent client.

patents live in s2-public-api next to papers, under ``/graph/v1/patent``.
defaults to the ``semantic_scholar`` base url and auth token.
``ASTA_PATENT_URL`` overrides ``apis.patent.base_url``.
point it at a local s2-public-api, e.g. ``http://localhost:8089``.
the gateway token rides along as a bearer header, so only point it at hosts you trust.

endpoints (firs2#150):
  - GET /graph/v1/patent/search
  - GET /graph/v1/patent/<ucid>
  - GET /graph/v1/patent/outbound-citations/<paper_id>

an unfed cluster returns 503.
calls surface it verbatim.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config, get_config_path
from asta.utils.headers import identity_headers

_TIMEOUT = 30  # seconds


class PatentClient:
    """client for the s2 public api patent endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        access_token: str | None = None,
    ):
        # asta.conf defaults apis.patent.base_url to the semantic_scholar base.
        if base_url is None:
            try:
                base_url = get_api_config("patent").get("base_url")
            except (KeyError, FileNotFoundError):
                base_url = None

        if not base_url:
            raise ValueError(
                f"No value for apis.patent.base_url in {get_config_path()}"
            )

        if access_token is None:
            access_token = get_access_token()

        self.base_url = base_url
        self.access_token = access_token
        self.headers = {
            **identity_headers(),
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """get a path from the api and decode the json body."""
        url = f"{self.base_url}{path}"
        if params:
            params = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers=self.headers)
        try:
            response = urllib.request.urlopen(req, timeout=_TIMEOUT)
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
        """bm25 search over title, abstract, brief summary, claims, and parties.

        Args:
            query: search query.
            fields: comma-separated patent fields. the api always adds ``ucid``.
            limit: max results, clamped to 100.
            offset: start of the batch.
        """
        params = {
            "query": query,
            "fields": fields,
            "limit": min(limit, 100),
            "offset": offset,
        }
        return self._request("/graph/v1/patent/search", params)

    def get_patent(self, ucid: str, fields: str | None = None) -> dict[str, Any]:
        """get one patent by ucid.

        Args:
            ucid: office + doc number + kind, no separators, e.g. ``US10123456B2``.
            fields: comma-separated patent fields. only detail returns ``claims`` and ``briefSummary``.
        """
        params = {"fields": fields} if fields else None
        ucid_quoted = urllib.parse.quote(ucid, safe="")
        return self._request(f"/graph/v1/patent/{ucid_quoted}", params)

    def outbound_citations(
        self,
        paper_id: str | int,
        fields: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """list patents that cite a paper.

        Args:
            paper_id: any s2 paper id, e.g. ``CorpusId:215416146`` or ``DOI:...``.
                a bare integer is a corpus id. the api 404s on it unprefixed.
            fields: comma-separated patent fields.
            limit: max results, clamped to 100.
            offset: start of the batch.
        """
        paper_id = str(paper_id)
        if paper_id.isdigit():
            paper_id = f"CorpusId:{paper_id}"
        params = {
            "fields": fields,
            "limit": min(limit, 100),
            "offset": offset,
        }
        paper_id_quoted = urllib.parse.quote(paper_id, safe=":")
        return self._request(
            f"/graph/v1/patent/outbound-citations/{paper_id_quoted}", params
        )
