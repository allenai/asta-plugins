"""Semantic Scholar API client"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config, get_config_path


class SemanticScholarClient:
    """Client for Semantic Scholar API"""

    def __init__(
        self,
        base_url: str | None = None,
        access_token: str | None = None,
    ):
        # Load base URL from config if not provided
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

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request to the API"""
        url = f"{self.base_url}{path}"
        if params:
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers=self.headers)
        try:
            response = urllib.request.urlopen(req)
            return json.loads(response.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise Exception(f"API error {e.code}: {error_body}")

    def get_paper(self, paper_id: str, fields: str | None = None) -> dict[str, Any]:
        """Get paper details by ID

        Args:
            paper_id: Paper ID (can be CorpusId:123, DOI:..., ARXIV:..., etc.)
            fields: Comma-separated list of fields to return
        """
        params = {"fields": fields} if fields else None
        return self._request(f"/graph/v1/paper/{paper_id}", params)

    def search_papers(
        self,
        query: str,
        fields: str | None = None,
        limit: int = 50,
        year: str | None = None,
        publication_date_or_year: str | None = None,
    ) -> dict[str, Any]:
        """Search papers by keyword

        Args:
            query: Search query
            fields: Comma-separated fields to return
            limit: Max results (default 50, max 100)
            year: Year filter (e.g., "2020", "2020-2024", "2020-")
            publication_date_or_year: Date range filter (e.g., ":2024-12-31", "2020:2024")
        """
        params = {
            "query": query,
            "fields": fields,
            "limit": min(limit, 100),
            "year": year,
            "publicationDateOrYear": publication_date_or_year,
        }
        return self._request("/graph/v1/paper/search", params)

    def get_paper_citations(
        self,
        paper_id: str,
        fields: str | None = None,
        limit: int = 100,
        publication_date_or_year: str | None = None,
    ) -> dict[str, Any]:
        """Get papers that cite this paper

        Args:
            paper_id: Paper ID
            fields: Comma-separated fields for citing papers
            limit: Max results (default 100, max 1000)
            publication_date_or_year: Date range filter (e.g., ":2024-12-31")
        """
        params = {
            "fields": fields,
            "limit": min(limit, 1000),
            "publicationDateOrYear": publication_date_or_year,
        }
        return self._request(f"/graph/v1/paper/{paper_id}/citations", params)

    def get_paper_references(
        self,
        paper_id: str,
        fields: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get papers that this paper references

        Args:
            paper_id: Paper ID
            fields: Comma-separated fields for referenced papers
            limit: Max results (default 100, max 1000)
        """
        params = {"fields": fields, "limit": min(limit, 1000)}
        return self._request(f"/graph/v1/paper/{paper_id}/references", params)

    def search_author(self, name: str, limit: int = 10) -> dict[str, Any]:
        """Search for authors by name

        Args:
            name: Author name
            limit: Max results (default 10, max 1000)
        """
        params = {"query": name, "limit": min(limit, 1000)}
        return self._request("/graph/v1/author/search", params)

    def get_author_papers(
        self,
        author_id: str,
        fields: str | None = None,
        limit: int = 100,
        publication_date_or_year: str | None = None,
    ) -> dict[str, Any]:
        """Get papers by an author

        Args:
            author_id: Author ID from search
            fields: Comma-separated fields to return
            limit: Max results (default 100, max 1000)
            publication_date_or_year: Date range filter (e.g., ":2024-12-31")
        """
        params = {
            "fields": fields,
            "limit": min(limit, 1000),
            "publicationDateOrYear": publication_date_or_year,
        }
        return self._request(f"/graph/v1/author/{author_id}/papers", params)
