"""Shared client-identification headers for Asta HTTP clients.

Every request this CLI makes to an Asta gateway backend carries these headers so
server-side telemetry can attribute traffic to the CLI and to a specific release.
Stdlib-only — this imports just the package version string, honoring the
core-client constraint in the developer guide.
"""

from asta import __version__

USER_AGENT = f"asta-cli/{__version__}"


def identity_headers() -> dict[str, str]:
    """Client-identification headers sent on every gateway request.

    - ``User-Agent``: ``asta-cli/<version>`` — replaces the urllib/httpx default
      that otherwise identifies the HTTP library rather than this project.
    - ``X-Asta-Client``: ``cli`` — the call path (as opposed to ``mcp``/``a2a``
      front-ends that reuse the same backends).
    - ``X-Asta-Client-Version``: the package version, so adoption/upgrade rate
      after a release is answerable from server-side telemetry.

    Deliberately omits an ``X-Asta-Skill`` header. The CLI cannot verify the
    invoking skill without brittle caller-threaded state, and each backend
    endpoint already maps 1:1 to a CLI sub-command via its URL path, so the
    finest grain the CLI can honestly report is already visible server-side.
    These are client-identification headers only — no request content or user
    data is added.
    """
    return {
        "User-Agent": USER_AGENT,
        "X-Asta-Client": "cli",
        "X-Asta-Client-Version": __version__,
    }
