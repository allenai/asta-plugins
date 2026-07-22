"""Forward citations command: patents that cite a given paper."""

import json

import click

from asta.patents.client import PatentClient
from asta.patents.search import _format_patent_results

DEFAULT_FIELDS = "ucid,title,publicationDate,assignees"


@click.command(name="forward-citations")
@click.argument("corpus_id", type=int)
@click.option(
    "--fields",
    default=DEFAULT_FIELDS,
    help="Comma-separated fields to return (ucid is always included)",
)
@click.option(
    "--limit",
    type=int,
    default=10,
    help="Maximum number of results (max 100)",
)
@click.option(
    "--offset",
    type=int,
    default=0,
    help="Starting position of the batch",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def forward_citations(
    corpus_id: int, fields: str, limit: int, offset: int, output_format: str
):
    """List patents that cite a given paper (corpus_id -> patents).

    CORPUS_ID is the S2 corpusId of the paper.

    Examples:

        asta patent forward-citations 215416146

        asta patent forward-citations 215416146 --limit 20
    """
    try:
        client = PatentClient()
        result = client.forward_citations(
            corpus_id, fields=fields, limit=limit, offset=offset
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            _format_patent_results(result)

    except Exception as e:
        raise click.ClickException(str(e))
