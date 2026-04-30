from asta_agent.a2a.commands import make_a2a_group

from asta.utils.config import get_api_config


def _auto_exp_designer_url() -> str:
    return get_api_config("auto-exp-designer")["base_url"]


auto_exp_designer = make_a2a_group(
    name="auto-exp-designer",
    url_factory=_auto_exp_designer_url,
    help=(
        "Design computational experiments via the Auto Experiment Designer agent.\n\n"
        "Subcommands talk to the agent through asta-gateway. Auth comes from\n"
        "`asta auth login` by default (or --api-key / $ASTA_A2A_API_KEY)."
    ),
)
