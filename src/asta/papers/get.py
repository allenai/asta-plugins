"""Get paper details command"""

import json

import click

from asta.papers.client import SemanticScholarClient


@click.command()
@click.argument("paper_id")
@click.option(
    "--fields",
    default="title,abstract,authors,year,venue,citationCount,publicationDate,url",
    help="Comma-separated fields to return",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def get(paper_id: str, fields: str, output_format: str):
    """Get details for a paper by ID.

    PAPER_ID can be:
    - CorpusId:215416146
    - DOI:10.18653/v1/N18-3011
    - ARXIV:2106.15928
    - PMID:19872477
    - URL:https://arxiv.org/abs/2106.15928

    Examples:

        asta papers get ARXIV:2005.14165

        asta papers get "DOI:10.18653/v1/N18-3011" --fields title,year,authors
    """
    try:
        client = SemanticScholarClient()
        result = client.get_paper(paper_id, fields=fields)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            # Text format
            click.echo(f"Title: {result.get('title', 'N/A')}")
            click.echo(f"Year: {result.get('year', 'N/A')}")
            if authors := result.get("authors"):
                author_names = ", ".join(a["name"] for a in authors[:5])
                if len(authors) > 5:
                    author_names += f", et al. ({len(authors)} total)"
                click.echo(f"Authors: {author_names}")
            click.echo(f"Venue: {result.get('venue', 'N/A')}")
            click.echo(f"Citations: {result.get('citationCount', 0)}")
            if abstract := result.get("abstract"):
                click.echo(f"\nAbstract: {abstract}")
            if url := result.get("url"):
                click.echo(f"\nURL: {url}")

    except Exception as e:
        raise click.ClickException(str(e))
