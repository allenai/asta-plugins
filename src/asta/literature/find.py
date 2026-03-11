"""Find papers command"""

import json
from pathlib import Path

import click

from asta.core import AstaPaperFinder
from asta.literature.models import LiteratureSearchResult


@click.command()
@click.argument("query")
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    required=True,
    help="Output file path for the results (required)",
)
@click.option(
    "--timeout",
    type=int,
    default=300,
    help="Maximum time to wait for results (seconds)",
)
@click.option(
    "--mode",
    type=click.Choice(["infer", "fast", "diligent"]),
    default="infer",
    help="Search strategy: infer (auto-detect), fast (quick results), or diligent (comprehensive)",
)
def find(query: str, output: str, timeout: int, mode: str):
    """Find papers matching QUERY using Asta Paper Finder.

    Requires an output file path to save results.

    Examples:

        # Save to specific file
        asta literature find "machine learning in healthcare" -o results.json

        # With custom timeout
        asta literature find "transformers" -o results.json --timeout 60

        # Use fast mode for quick results
        asta literature find "deep learning" -o results.json --mode fast

        # Use diligent mode for comprehensive search
        asta literature find "neural networks" -o results.json --mode diligent
    """
    try:
        client = AstaPaperFinder()
        raw_result = client.find_papers(
            query, timeout=timeout, save_to_file=None, operation_mode=mode
        )

        # Transform to literature search result format
        literature_result = LiteratureSearchResult(
            query=raw_result["query"], results=raw_result["widget"]["results"]
        )

        # Convert to dict for output
        output_data = literature_result.model_dump(mode="json", exclude_none=False)

        # Use the specified output path
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

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
