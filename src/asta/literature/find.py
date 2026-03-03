"""Find papers command"""

import json
import re
from datetime import datetime
from pathlib import Path

import click

from asta.core import AstaPaperFinder
from asta.literature.models import LiteratureSearchResult


@click.command()
@click.argument("query")
@click.option(
    "--timeout",
    type=int,
    default=300,
    help="Maximum time to wait for results (seconds)",
)
def find(query: str, timeout: int):
    """Find papers matching QUERY using Asta Paper Finder.

    Saves results to .asta/literature/find/ with an auto-generated filename.

    Examples:

        # Save to default location
        asta literature find "machine learning in healthcare"

        # With custom timeout
        asta literature find "transformers" --timeout 60
    """
    try:
        client = AstaPaperFinder()
        raw_result = client.find_papers(query, timeout=timeout, save_to_file=None)

        # Transform to literature search result format
        literature_result = LiteratureSearchResult(
            query=raw_result["query"], results=raw_result["widget"]["results"]
        )

        # Convert to dict for output
        output_data = literature_result.model_dump(mode="json", exclude_none=False)

        # Generate default path: .asta/literature/find/YYYY-MM-DD-HH-MM-SS-query-slug.json
        default_dir = Path.cwd() / ".asta" / "literature" / "find"
        default_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        # Create a slug from the query (lowercase, alphanumeric and hyphens only, max 50 chars)
        query_slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:50]
        filename = f"{timestamp}-{query_slug}.json"
        output_path = default_dir / filename

        # Save to file
        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2)

        # Print summary to stderr
        click.echo(f"Results saved to: {output_path}", err=True)

    except TimeoutError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(2)
    except Exception as e:
        raise click.ClickException(str(e))
