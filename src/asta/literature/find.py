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
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path. If not specified, saves to ~/.asta/literature/YYYY-MM-DD-HH-MM-SS-query.json. Use '-' to write to stdout.",
)
def find(query: str, timeout: int, output: Path | None):
    """Find papers matching QUERY using Asta Paper Finder.

    Saves results to ~/.asta/literature/ by default with an auto-generated filename.
    Use -o to specify a custom output path, or -o - to write to stdout.

    Examples:

        # Save to default location
        asta literature find "machine learning in healthcare"

        # Save to custom path
        asta literature find "deep learning" -o results.json

        # Write to stdout
        asta literature find "transformers" -o -

        # Save to custom path with timeout
        asta literature find "transformers" --timeout 60 -o /tmp/papers.json
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

        # Determine output path
        write_to_stdout = False
        if output is None:
            # Generate default path: ~/.asta/literature/YYYY-MM-DD-HH-MM-SS-query-slug.json
            default_dir = Path.home() / ".asta" / "literature"
            default_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            # Create a slug from the query (lowercase, alphanumeric and hyphens only, max 50 chars)
            query_slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:50]
            filename = f"{timestamp}-{query_slug}.json"
            output = default_dir / filename
        elif str(output) == "-":
            # Special case: write to stdout
            write_to_stdout = True

        if write_to_stdout:
            # Print to stdout
            click.echo(json.dumps(output_data, indent=2))
        else:
            # Save to file
            with open(output, "w") as f:
                json.dump(output_data, f, indent=2)

            # Print summary to stderr
            click.echo("Search completed successfully!", err=True)
            click.echo(f"Papers found: {len(literature_result.results)}", err=True)
            click.echo(f"Results saved to: {output}", err=True)

    except TimeoutError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(2)
    except Exception as e:
        raise click.ClickException(str(e))
