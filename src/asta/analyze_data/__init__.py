from asta_agent.a2a.commands import make_a2a_group

from asta.analyze_data._url import dv_url
from asta.analyze_data.poll import poll as poll_cmd
from asta.analyze_data.upload import upload as upload_cmd
from asta.utils.auth_helper import get_access_token

analyze_data = make_a2a_group(
    name="analyze-data",
    url_factory=dv_url,
    token_factory=get_access_token,
    help=(
        "Analyze datasets via the Ai2 DataVoyager agent.\n\n"
        "Workflow: mint a UUID, `upload` your local files under that "
        "context-id, then `send-message --context-id <uuid>` with a JSON "
        "payload referencing the returned s3_uris. Re-using the same "
        "context-id resumes the session and adds files to the same "
        "workspace.\n\n"
        "Auth comes from `asta auth login`."
    ),
)
analyze_data.add_command(upload_cmd)
analyze_data.add_command(poll_cmd)
