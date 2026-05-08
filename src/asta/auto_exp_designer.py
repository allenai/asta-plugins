import os

from asta_agent.a2a.commands import make_a2a_group

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config


def _auto_exp_designer_url() -> str:
    return get_api_config("auto-exp-designer")["base_url"]


def _auto_exp_designer_token() -> str | None:
    if env := (os.environ.get("ASTA_A2A_API_KEY") or os.environ.get("API_KEY")):
        return env
    try:
        return get_access_token()
    except Exception:
        return None


auto_exp_designer = make_a2a_group(
    name="auto-exp-designer",
    url_factory=_auto_exp_designer_url,
    token_factory=_auto_exp_designer_token,
    help=(
        "Design computational experiments via the Auto Experiment Designer agent.\n\n"
        "Subcommands talk to the agent through asta-gateway. Auth comes from\n"
        "`asta auth login` by default (or --api-key / $ASTA_A2A_API_KEY)."
    ),
)
