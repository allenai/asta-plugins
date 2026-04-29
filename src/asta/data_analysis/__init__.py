from asta_agent.a2a.commands import make_a2a_group

from asta.data_analysis.analyze import _dv_url, analyze as analyze_cmd
from asta.data_analysis.upload import upload as upload_cmd


data_analysis = make_a2a_group(
    name="analyze-data",
    url_factory=_dv_url,
    help=(
        "Analyze datasets via the Ai2 DataVoyager agent.\n\n"
        "Primary command: `analyze` — pass one or more local files and a "
        "query; the CLI uploads them into your workspace and submits the "
        "analysis.\n\n"
        "Auth comes from `asta auth login`.\n\n"
        "`upload` is a standalone helper for scripting or testing — most "
        "users don't need it."
    ),
)
data_analysis.add_command(analyze_cmd)
data_analysis.add_command(upload_cmd)
