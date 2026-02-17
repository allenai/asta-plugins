"""Search papers command"""

import json

import click

from asta.papers.client import SemanticScholarClient


@click.command()
@click.argument("query")
@click.option(
    "--fields",
    default="title,authors,year,venue,citationCount",
    help="Comma-separated fields to return",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum number of results (max 100)",
)
@click.option(
    "--year",
    help="Year filter (e.g., 2020, 2020-2024, 2020-)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def search(query: str, fields: str, limit: int, year: str | None, output_format: str):
    """Search for papers by keyword.

    Examples:

        asta papers search "transformers attention mechanism"

        asta papers search "RLHF" --year 2023- --limit 10

        asta papers search "neural networks" --fields title,year,abstract
    """
    try:
        client = SemanticScholarClient()
        result = client.search_papers(query, fields=fields, limit=limit, year=year)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            # Text format
            papers = result.get("data", [])
            click.echo(f"Found {result.get('total', len(papers))} papers\n")

            for i, paper in enumerate(papers, 1):
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
