"""Get citations command"""

import json

import click

from asta.papers.client import SemanticScholarClient


@click.command()
@click.argument("paper_id")
@click.option(
    "--fields",
    default="title,authors,year,venue,citationCount",
    help="Comma-separated fields to return",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    help="Maximum number of citations (max 1000)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def citations(paper_id: str, fields: str, limit: int, output_format: str):
    """Get papers that cite a given paper.

    PAPER_ID format same as 'asta papers get' command.

    Examples:

        asta papers citations ARXIV:2005.14165

        asta papers citations "CorpusId:218487638" --limit 20
    """
    try:
        # Create client (loads config and auth token automatically)
        client = SemanticScholarClient()
        result = client.get_paper_citations(paper_id, fields=fields, limit=limit)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            # Text format
            citations = result.get("data", [])
            click.echo(f"Found {len(citations)} citing papers\n")

            for i, item in enumerate(citations, 1):
                paper = item.get("citingPaper", {})
                click.echo(f"{i}. {paper.get('title', 'N/A')}")
                if authors := paper.get("authors"):
                    author_names = ", ".join(a["name"] for a in authors[:3])
                    if len(authors) > 3:
                        author_names += " et al."
                    click.echo(f"   Authors: {author_names}")
                year_venue = []
                if y := paper.get("year"):
                    year_venue.append(str(y))
                if v := paper.get("venue"):
                    year_venue.append(v)
                if year_venue:
                    click.echo(f"   {' - '.join(year_venue)}")
                if cites := paper.get("citationCount"):
                    click.echo(f"   Citations: {cites}")
                click.echo()

    except Exception as e:
        raise click.ClickException(str(e))
