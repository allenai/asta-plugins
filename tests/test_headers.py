"""Tests for shared client-identification headers."""

from asta import __version__
from asta.utils.headers import identity_headers


def test_identity_headers_values():
    headers = identity_headers()
    assert headers["User-Agent"] == f"asta-cli/{__version__}"
    assert headers["X-Asta-Client"] == "cli"
    assert headers["X-Asta-Client-Version"] == __version__


def test_identity_headers_omits_skill():
    # The CLI cannot verify the invoking skill, so it sends no X-Asta-Skill.
    assert "X-Asta-Skill" not in identity_headers()


def test_identity_headers_are_strings():
    # urllib/httpx require str header values.
    for key, value in identity_headers().items():
        assert isinstance(key, str)
        assert isinstance(value, str)


def test_clients_send_identity_headers():
    """Gateway clients merge identity headers without dropping their own."""
    from asta.literature import AstaPaperFinder
    from asta.papers.client import SemanticScholarClient

    for client in (
        AstaPaperFinder(base_url="https://example.test", access_token="t"),
        SemanticScholarClient(base_url="https://example.test", access_token="t"),
    ):
        assert client.headers["X-Asta-Client"] == "cli"
        assert client.headers["User-Agent"] == f"asta-cli/{__version__}"
        # Existing headers are preserved.
        assert client.headers["Authorization"] == "Bearer t"
        assert client.headers["Content-Type"] == "application/json"
