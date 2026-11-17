"""search patents command."""

import json

import click

from asta.patents.client import PatentClient
from asta.patents.format import format_patent_results

DEFAULT_FIELDS = "ucid,title,publicationDate,assignees"


@click.command()
@click.argument("query")
@click.option(
    "--fields",
    default=DEFAULT_FIELDS,
    help="comma-separated fields. ucid is always included.",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 100),
    default=10,
    help="max results, 1 to 100.",
)
@click.option(
    "--offset",
    type=click.IntRange(min=0),
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
def search(query: str, fields: str, limit: int, offset: int, output_format: str):
    """bm25 search over the patent corpus.

    matches title, abstract, brief summary, claims, and party names.

    Examples:

        asta patents search "graphene battery electrode"

        asta patents search "mRNA vaccine" --limit 20 --fields ucid,title,assignees
    """
    try:
        client = PatentClient()
        result = client.search(query, fields=fields, limit=limit, offset=offset)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            format_patent_results(result)

    except Exception as e:
        raise click.ClickException(str(e))
