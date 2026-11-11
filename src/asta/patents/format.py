"""text output for patent results."""

import click


def format_patent_results(result: dict) -> None:
    """print search or citation results as text."""
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
