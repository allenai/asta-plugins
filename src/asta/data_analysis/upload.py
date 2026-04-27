"""`asta data-analysis upload` — standalone upload helper.

Most users should prefer `analyze`, which does the upload implicitly. This
command exists for scripting (emit a URI without submitting an analysis)
and for exercising the upload endpoint in isolation.
"""

from __future__ import annotations

import html
import json
import sys

import click
from asta_agent.a2a.commands import _get_api_key

from asta.data_analysis._client import upload_local_file
from asta.utils.config import get_api_config


def _dv_url() -> str:
    return get_api_config("data_analysis")["base_url"]


@click.command()
@click.argument(
    "file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--api-key",
    default=None,
    help="Bearer token (falls back to ASTA_A2A_API_KEY or `asta auth`).",
)
@click.option("--filename", default=None, help="Override the uploaded object's name.")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit {s3_uri, attachment_tag, filename, size, content_type} as JSON.",
)
def upload(
    file: str,
    api_key: str | None,
    filename: str | None,
    as_json: bool,
) -> None:
    """Upload a local FILE into your DataVoyager workspace."""
    token = _get_api_key(api_key)
    base_url = _dv_url()

    try:
        result = upload_local_file(base_url, token, file, filename=filename)
    except FileNotFoundError as e:
        raise click.UsageError(str(e)) from e
    except ValueError as e:
        raise click.UsageError(str(e)) from e
    except Exception as e:
        click.echo(json.dumps({"error": {"message": str(e)}}, indent=2), err=True)
        sys.exit(1)

    s3_uri = result["s3_uri"]
    name = result["filename"]
    tag = (
        f'<astaattachment s3_uri="{html.escape(s3_uri, quote=True)}">'
        f'{html.escape(name)}</astaattachment>'
    )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "s3_uri": s3_uri,
                    "attachment_tag": tag,
                    "filename": name,
                    "size": result["size"],
                    "content_type": result["content_type"],
                },
                indent=2,
            )
        )
    else:
        click.echo(tag)
        click.echo(f"s3_uri: {s3_uri}")
