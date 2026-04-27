"""`asta data-analysis analyze` — one-step upload + submit."""

from __future__ import annotations

import json
import os
import sys

import click
from asta_agent.a2a.client import A2AClient, A2AError
from asta_agent.a2a.commands import _get_api_key

from asta.data_analysis._client import upload_local_file
from asta.utils.config import get_api_config


def _dv_url() -> str:
    return get_api_config("data_analysis")["base_url"]


@click.command()
@click.argument(
    "datasets",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option("--query", required=True, help="The research question to analyze.")
@click.option(
    "--api-key",
    default=None,
    help="Bearer token (falls back to ASTA_A2A_API_KEY or `asta auth`).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Print the raw A2A response JSON instead of a summary.",
)
def analyze(
    datasets: tuple[str, ...],
    query: str,
    api_key: str | None,
    as_json: bool,
) -> None:
    """Upload DATASETS and run a DataVoyager analysis.

    DATASETS are one or more local file paths. Each is uploaded into your
    workspace and then referenced by the analysis. The CLI handles the S3
    hand-off — you never need to mint attachment tags manually.

    Example:

        asta data-analysis analyze ./titanic.csv \\
            --query "What differs between survivors and non-survivors?"
    """
    token = _get_api_key(api_key)
    base_url = _dv_url()

    s3_uris: list[str] = []
    for path in datasets:
        try:
            result = upload_local_file(base_url, token, path)
        except FileNotFoundError as e:
            raise click.UsageError(str(e)) from e
        except ValueError as e:
            raise click.UsageError(str(e)) from e
        s3_uris.append(result["s3_uri"])
        click.echo(f"uploaded: {path} -> {result['s3_uri']}", err=True)

    payload = {
        "kind": "analyze-data",
        "data": {"tool_request": {"query": query, "datasets": s3_uris}},
    }

    try:
        response = A2AClient(base_url, api_key=token).send_message(
            json.dumps(payload)
        )
    except A2AError as e:
        click.echo(
            json.dumps({"error": {"code": e.code, "message": str(e)}}, indent=2),
            err=True,
        )
        sys.exit(1)
    except Exception as e:
        click.echo(json.dumps({"error": {"message": str(e)}}, indent=2), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(response, indent=2))
        return

    task_id = response.get("id") or response.get("taskId") or "<unknown>"
    state = (
        (response.get("status") or {}).get("state")
        if isinstance(response.get("status"), dict)
        else None
    )
    click.echo(f"task_id: {task_id}")
    if state:
        click.echo(f"state:   {state}")
    click.echo("poll with: asta data-analysis task " + str(task_id))
