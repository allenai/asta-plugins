"""Snippet search papers command"""

import json
import os

import click

from asta.papers.client import SemanticScholarClient


@click.command("snippet-search")
@click.argument("query")
@click.option(
    "--fields",
    default="snippet.text,snippet.snippetKind",
    help="Comma-separated snippet fields to return (e.g., snippet.text,snippet.section)",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum number of results (max 1000)",
)
@click.option(
    "--date",
    help="Date or year filter (e.g., 2020, 2020-2024, 2024-01-01:2024-12-31, 2020-)",
)
@click.option(
    "--inserted-before",
    default=None,
    help="Only include papers indexed before this date (YYYY-MM-DD, YYYY-MM, or YYYY)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def snippet_search(
    query: str,
    fields: str,
    limit: int,
    date: str | None,
    inserted_before: str | None,
    output_format: str,
):
    """Search for papers with full-text snippet matching.

    Uses the S2 snippet/search API to find matching text excerpts
    from paper titles, abstracts, and bodies.

    Examples:

        asta papers snippet-search "in-context learning emerges at scale"

        asta papers snippet-search "RLHF reward hacking" --date 2023- --limit 10

        asta papers snippet-search "chain-of-thought" --inserted-before 2024-01-01
    """
    try:
        client = SemanticScholarClient()
        publication_date_or_year = date or os.environ.get("ASTA_PUBLICATION_DATE_RANGE")

        result = client.snippet_search(
            query,
            fields=fields,
            limit=limit,
            publication_date_or_year=publication_date_or_year,
            inserted_before=inserted_before,
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            _format_snippet_results(result)

    except Exception as e:
        raise click.ClickException(str(e))


def _format_snippet_results(result: dict) -> None:
    """Format snippet search results as text."""
    data = result.get("data", [])
    click.echo(f"Found {len(data)} snippet results\n")

    for i, entry in enumerate(data, 1):
        paper = entry.get("paper", {})
        title = paper.get("title", "N/A")
        click.echo(f"{i}. {title}")
        if authors := paper.get("authors"):
            author_names = ", ".join(a.get("name", "") for a in authors[:3])
            if len(authors) > 3:
                author_names += " et al."
            click.echo(f"   Authors: {author_names}")
        if score := entry.get("score"):
            click.echo(f"   Score: {score}")
        snippet = entry.get("snippet", {})
        if snippet_text := snippet.get("text"):
            click.echo(
                f"   Snippet: {snippet_text[:300]}{'...' if len(snippet_text) > 300 else ''}"
            )
        if snippet_kind := snippet.get("snippetKind"):
            click.echo(f"   Kind: {snippet_kind}")
        click.echo()
