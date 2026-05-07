import os

from asta_agent.a2a.commands import make_a2a_group

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config


def _theorizer_url() -> str:
    """Resolve the Theorizer base URL.

    ``$ASTA_THEORIZER_URL`` takes precedence — useful for pointing
    directly at a locally-running theorizer (skipping the gateway) for
    development or skill-level integration tests.
    """
    if direct := os.environ.get("ASTA_THEORIZER_URL"):
        return direct
    return get_api_config("theorizer")["base_url"]


def _theorizer_token() -> str | None:
    """Bearer token resolver.

    1. Honour ``$ASTA_A2A_API_KEY`` / ``$API_KEY`` for direct-to-agent
       runs (set alongside ``$ASTA_THEORIZER_URL``).
    2. Otherwise fall through to ``asta auth login`` (Auth0 JWT for the
       gateway).
    """
    if env := (os.environ.get("ASTA_A2A_API_KEY") or os.environ.get("API_KEY")):
        return env
    try:
        return get_access_token()
    except Exception:
        return None


generate_theories = make_a2a_group(
    name="generate-theories",
    url_factory=_theorizer_url,
    token_factory=_theorizer_token,
    help=(
        "Generate scientific theories via the Ai2 Theorizer agent.\n\n"
        "Subcommands talk to the Theorizer through asta-gateway by default. "
        "Set $ASTA_THEORIZER_URL to point at a local instance and "
        "$ASTA_A2A_API_KEY for its bearer token. Otherwise auth comes from "
        "`asta auth login`."
    ),
)
