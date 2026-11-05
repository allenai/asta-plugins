"""contract tests for PatentClient against the live s2 public api.

mocked tests only check the path the client builds.
these catch a renamed or removed route.
network failures and rate limits skip instead of failing.
"""

import urllib.error

import pytest

from asta.patents.client import PatentClient

S2_API = "https://api.semanticscholar.org"

# a paper cited by 100+ patents, stable enough for a contract test.
CITED_CORPUS_ID = 98279155


@pytest.fixture
def client() -> PatentClient:
    return PatentClient(base_url=S2_API, access_token="")


@pytest.fixture(autouse=True)
def skip_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """skip on network errors and 429s, fail on anything else."""
    real = PatentClient._request

    def guarded(self: PatentClient, path: str, params: dict | None = None):
        try:
            return real(self, path, params)
        except urllib.error.URLError as e:
            pytest.skip(f"s2 api unreachable: {e}")
        except Exception as e:
            if "API error 429" in str(e):
                pytest.skip("s2 api rate limited")
            raise

    monkeypatch.setattr(PatentClient, "_request", guarded)


def test_outbound_citations_bare_corpus_id(client: PatentClient) -> None:
    result = client.outbound_citations(CITED_CORPUS_ID, limit=1)
    assert result["total"] > 0, "a well-cited paper should have citing patents"


def test_outbound_citations_prefixed_id(client: PatentClient) -> None:
    result = client.outbound_citations(f"CorpusId:{CITED_CORPUS_ID}", limit=1)
    assert result["total"] > 0


def test_search(client: PatentClient) -> None:
    result = client.search("graphene battery", fields="ucid,title", limit=1)
    assert result["data"][0]["ucid"]


def test_get_patent(client: PatentClient) -> None:
    hit = client.search("graphene battery", limit=1)["data"][0]
    result = client.get_patent(hit["ucid"], fields="ucid,title")
    assert result["ucid"] == hit["ucid"]
