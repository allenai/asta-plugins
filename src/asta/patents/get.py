"""get patent detail command."""

import json

import click

from asta.patents.client import PatentClient

# claims and briefSummary are left out by default because they can be huge.
# request them with --fields.
DEFAULT_FIELDS = (
    "ucid,title,abstract,assignees,inventors,"
    "publicationDate,filingDate,cpcCodes,citedPaperCorpusIds"
)


@click.command()
@click.argument("ucid")
@click.option(
    "--fields",
    default=DEFAULT_FIELDS,
    help="comma-separated fields. add claims,briefSummary for full text.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="output format.",
)
def get(ucid: str, fields: str, output_format: str):
    """get one patent by ucid.

    ucid is office + doc number + kind with no separators, e.g. US10123456B2.

    Examples:

        asta patents get US10123456B2

        asta patents get US10123456B2 --fields ucid,title,claims,briefSummary
    """
    try:
        client = PatentClient()
        result = client.get_patent(ucid, fields=fields)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Title: {result.get('title', 'N/A')}")
            click.echo(f"UCID: {result.get('ucid', 'N/A')}")
            if assignees := result.get("assignees"):
                click.echo(f"Assignees: {', '.join(assignees)}")
            if inventors := result.get("inventors"):
                click.echo(f"Inventors: {', '.join(inventors)}")
            if date := result.get("publicationDate"):
                click.echo(f"Published: {date}")
            if date := result.get("filingDate"):
                click.echo(f"Filed: {date}")
            if cpc := result.get("cpcCodes"):
                click.echo(f"CPC: {', '.join(cpc)}")
            if cited := result.get("citedPaperCorpusIds"):
                click.echo(f"Cites (corpusIds): {', '.join(str(c) for c in cited)}")
            if abstract := result.get("abstract"):
                click.echo(f"\nAbstract: {abstract}")

    except Exception as e:
        raise click.ClickException(str(e))
