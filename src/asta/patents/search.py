"""Search patents command."""

import json

import click

from asta.patents.client import PatentClient

DEFAULT_FIELDS = "ucid,title,publicationDate,assignees"


@click.command()
@click.argument("query")
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
def search(query: str, fields: str, limit: int, offset: int, output_format: str):
    """BM25 lexical search over the patent corpus.

    Searches title, abstract, claims, and specification.

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
            _format_patent_results(result)

    except Exception as e:
        raise click.ClickException(str(e))


def _format_patent_results(result: dict) -> None:
    """Format patent search / citation results as text."""
    patents = result.get("data", [])
    click.echo(f"Found {result.get('total', len(patents))} patents\n")

    for i, patent in enumerate(patents, 1):
        click.echo(f"{i}. {patent.get('title', 'N/A')}")
        if ucid := patent.get("ucid"):
            click.echo(f"   UCID: {ucid}")
        if assignees := patent.get("assignees"):
            names = ", ".join(assignees[:3])
            if len(assignees) > 3:
                names += " et al."
            click.echo(f"   Assignees: {names}")
        if date := patent.get("publicationDate"):
            click.echo(f"   Published: {date}")
        click.echo()
