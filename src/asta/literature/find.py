"""Find papers command"""

import json
from pathlib import Path

import click

from asta.core import AstaPaperFinder
from asta.literature.models import LiteratureSearchResult
from asta.literature.threads import (
    create_initial_state,
    save_results,
    session_dir,
)


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
    help="Output file path. Use '-' to write to stdout instead of session folder.",
)
def find(query: str, timeout: int, output: Path | None):
    """Find papers matching QUERY using Asta Paper Finder.

    Results are saved to a session folder under ~/.asta/literature/sessions/.
    Use -o to specify a custom output path, or -o - to write to stdout.

    Examples:

        asta literature find "machine learning in healthcare"

        asta literature find "deep learning" -o results.json

        asta literature find "transformers" -o -
    """
    try:
        client = AstaPaperFinder()
        raw_result = client.find_papers(query, timeout=timeout, save_to_file=None)

        literature_result = LiteratureSearchResult(
            query=raw_result["query"], results=raw_result["widget"]["results"]
        )
        output_data = literature_result.model_dump(mode="json", exclude_none=False)
        response_text = raw_result.get("response", "")

        write_to_stdout = str(output) == "-" if output is not None else False

        if write_to_stdout:
            click.echo(json.dumps(output_data, indent=2))
            return

        # Create thread state (sets up session folder)
        thread_id = raw_result.get("thread_id", "")
        widget_id = raw_result.get("widget_id", "")

        if thread_id:
            state = create_initial_state(
                thread_id=thread_id,
                widget_id=widget_id,
                query=query,
                results=raw_result["widget"]["results"],
                user_id=client.user_id,
            )
            # Save results into session folder (include agent response)
            output_data["response"] = response_text
            results_path = save_results(
                state.session_slug,
                1,
                query,
                output_data,
            )
            sess_dir = session_dir(state.session_slug)
        else:
            results_path = None
            sess_dir = None

        # Also save to custom output if specified
        if output is not None:
            with open(output, "w") as f:
                json.dump(output_data, f, indent=2)

        # Print agent response to stdout
        if response_text:
            click.echo(response_text)

        # Print summary to stderr
        click.echo("Search completed successfully!", err=True)
        click.echo(f"Thread: {thread_id}", err=True)
        click.echo(f"Papers found: {len(literature_result.results)}", err=True)
        if sess_dir:
            click.echo(f"Session: {sess_dir}", err=True)
        if results_path:
            click.echo(f"Results: {results_path}", err=True)
        if output is not None:
            click.echo(f"Output: {output}", err=True)
        if thread_id:
            click.echo(f"Asta: {client.base_url}/share/{thread_id}", err=True)

    except TimeoutError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(2)
    except Exception as e:
        raise click.ClickException(str(e))
