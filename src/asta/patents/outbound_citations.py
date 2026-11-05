"""outbound citations command."""

import json

import click

from asta.patents.client import PatentClient
from asta.patents.search import _format_patent_results

DEFAULT_FIELDS = "ucid,title,publicationDate,assignees"


@click.command(name="outbound-citations")
@click.argument("paper_id")
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
def outbound_citations(
    paper_id: str, fields: str, limit: int, offset: int, output_format: str
):
    """list patents that cite a paper.

    PAPER_ID is any s2 paper id, e.g. CorpusId:215416146 or ARXIV:2106.15928.
    a bare integer is treated as a corpus id.

    Examples:

        asta patents outbound-citations CorpusId:215416146

        asta patents outbound-citations 215416146 --limit 20
    """
    try:
        client = PatentClient()
        result = client.outbound_citations(
            paper_id, fields=fields, limit=limit, offset=offset
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            _format_patent_results(result)

    except Exception as e:
        raise click.ClickException(str(e))
