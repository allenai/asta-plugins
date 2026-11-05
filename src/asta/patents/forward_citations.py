"""forward citations command."""

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
    help="comma-separated fields. ucid is always included.",
)
@click.option(
    "--limit",
    type=int,
    default=10,
    help="max results, up to 100.",
)
@click.option(
    "--offset",
    type=int,
    default=0,
    help="start of the batch.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="output format.",
)
def forward_citations(
    corpus_id: int, fields: str, limit: int, offset: int, output_format: str
):
    """list patents that cite a paper.

    CORPUS_ID is the s2 corpusId of the paper.

    Examples:

        asta patents forward-citations 215416146

        asta patents forward-citations 215416146 --limit 20
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
