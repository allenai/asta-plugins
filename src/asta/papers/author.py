"""Author search and papers commands"""

import json

import click

from asta.papers.client import SemanticScholarClient


@click.group()
def author():
    """Author-related commands"""
    pass


@author.command(name="search")
@click.argument("name")
@click.option(
    "--limit",
    type=int,
    default=10,
    help="Maximum number of results (max 1000)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def search_author(name: str, limit: int, output_format: str):
    """Search for authors by name.

    Examples:

        asta papers author search "Yoav Goldberg"

        asta papers author search "Hinton" --limit 5
    """
    try:
        # Create client (loads config and auth token automatically)
        client = SemanticScholarClient()
        result = client.search_author(name, limit=limit)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            # Text format
            authors = result.get("data", [])
            click.echo(f"Found {len(authors)} authors\n")

            for i, author in enumerate(authors, 1):
                click.echo(f"{i}. {author.get('name', 'N/A')}")
                click.echo(f"   Author ID: {author.get('authorId', 'N/A')}")
                if affiliations := author.get("affiliations"):
                    click.echo(f"   Affiliations: {', '.join(affiliations)}")
                if paper_count := author.get("paperCount"):
                    click.echo(f"   Papers: {paper_count}")
                if citation_count := author.get("citationCount"):
                    click.echo(f"   Citations: {citation_count}")
                click.echo()

    except Exception as e:
        raise click.ClickException(str(e))


@author.command(name="papers")
@click.argument("author_id")
@click.option(
    "--fields",
    default="title,year,venue,citationCount",
    help="Comma-separated fields to return",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    help="Maximum number of papers (max 1000)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def author_papers(author_id: str, fields: str, limit: int, output_format: str):
    """Get papers by an author.

    Use AUTHOR_ID from 'asta papers author search' command.

    Examples:

        asta papers author papers 1741101

        asta papers author papers 1741101 --limit 10 --fields title,year
    """
    try:
        # Create client (loads config and auth token automatically)
        client = SemanticScholarClient()
        result = client.get_author_papers(author_id, fields=fields, limit=limit)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            # Text format
            papers = result.get("data", [])
            click.echo(f"Found {len(papers)} papers\n")

            for i, item in enumerate(papers, 1):
                paper = item.get("paper", {})
                click.echo(f"{i}. {paper.get('title', 'N/A')}")
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
