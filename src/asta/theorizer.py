from asta_agent.a2a.commands import make_a2a_group

from asta.utils.config import get_api_config


def _theorizer_url() -> str:
    return get_api_config("theorizer")["base_url"]


generate_theories = make_a2a_group(
    name="generate-theories",
    url_factory=_theorizer_url,
    help=(
        "Generate scientific theories via the Ai2 Theorizer agent.\n\n"
        "Subcommands talk to the Theorizer through asta-gateway. Auth comes from\n"
        "`asta auth login` by default (or --api-key / $ASTA_A2A_API_KEY)."
    ),
)
