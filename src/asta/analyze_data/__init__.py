from asta_agent.a2a.commands import make_a2a_group

from asta.analyze_data._url import dv_url
from asta.analyze_data.poll import poll as poll_cmd
from asta.analyze_data.submit import submit as submit_cmd
from asta.utils.auth_helper import get_access_token

analyze_data = make_a2a_group(
    name="analyze-data",
    url_factory=dv_url,
    token_factory=get_access_token,
    help=(
        "Analyze datasets via the Ai2 DataVoyager agent.\n\n"
        "Run `submit '<question>' file1 [file2 ...]` to start a new "
        "session, or `submit --context-id <uuid> '<follow-up>'` to ask a "
        "follow-up against the same workspace (optionally attaching more "
        "files). Use `poll <task-id>` to wait for completion.\n\n"
        "Auth comes from `asta auth login`."
    ),
)
analyze_data.add_command(submit_cmd)
analyze_data.add_command(poll_cmd)
