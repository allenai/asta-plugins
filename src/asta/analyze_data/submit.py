"""`asta analyze-data submit` — upload datasets and submit an analysis.

Replaces the prior multi-step flow (mint UUID, run ``upload``, build a JSON
payload, run ``send-message``) with a single command. New session: pass at
least one file and a fresh context-id is minted. Continuing session: pass
``--context-id`` and any new files (or none) — the agent reuses the
existing workspace.
"""

from __future__ import annotations

import json
import uuid

import click
from asta_agent.a2a.client import A2AClient, A2AError

from asta.analyze_data._request import build_envelope
from asta.analyze_data._upload import upload_local_file
from asta.analyze_data._url import dv_url
from asta.utils.auth_helper import get_access_token


@click.command()
@click.argument("query")
@click.argument(
    "files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--context-id",
    default=None,
    help="Continue an existing session. If omitted, a fresh context-id is "
    "minted and at least one FILE must be supplied.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write the A2A response JSON to PATH (default: stdout).",
)
def submit(
    query: str,
    files: tuple[str, ...],
    context_id: str | None,
    output: str | None,
) -> None:
    """Submit QUERY against FILES via the DataVoyager agent.

    With no ``--context-id``: mints a new session UUID; requires at least
    one FILE to upload.

    With ``--context-id``: reuses the named session; FILES are optional and
    (if provided) get uploaded into that session before the query runs.

    Auth: run ``asta auth login`` first.
    """
    if context_id is None and not files:
        raise click.UsageError(
            "submit requires at least one FILE when --context-id is not set."
        )

    ctx = context_id or str(uuid.uuid4())
    base_url = dv_url()
    token = get_access_token()

    s3_uris: list[str] = []
    for path in files:
        try:
            uploaded = upload_local_file(base_url, token, path, context_id=ctx)
        except Exception as e:
            raise click.ClickException(f"Failed to upload {path}: {e}") from e
        s3_uris.append(uploaded["s3_uri"])
        click.echo(f"uploaded: {path} -> {uploaded['s3_uri']}", err=True)

    envelope = build_envelope(query, s3_uris)
    client = A2AClient(base_url, api_key=token)
    try:
        result = client.send_message(json.dumps(envelope), context_id=ctx)
    except A2AError as e:
        click.echo(
            json.dumps({"error": {"code": e.code, "message": str(e)}}, indent=2),
            err=True,
        )
        raise click.exceptions.Exit(1) from e

    payload = json.dumps(result, indent=2)
    if output:
        with open(output, "w") as f:
            f.write(payload)
    else:
        click.echo(payload)
