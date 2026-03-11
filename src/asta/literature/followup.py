"""Follow-up command for multi-turn literature threads."""

from datetime import UTC, datetime

import click

from asta.core import AstaPaperFinder
from asta.literature.models import Turn
from asta.literature.threads import (
    format_paper_line,
    require_thread_state,
    save_results,
    session_dir,
    update_thread_turn,
)


@click.command()
@click.argument("thread_id")
@click.argument("message")
@click.option(
    "--timeout",
    type=int,
    default=300,
    help="Maximum time to wait for results (seconds)",
)
def followup(thread_id: str, message: str, timeout: int):
    """Send a follow-up MESSAGE to an existing search thread.

    Continues the conversation in THREAD_ID with any follow-up — refinements,
    new angles, clarifications, or related questions.

    Examples:

        asta literature followup abc123 "focus on diffusion models"

        asta literature followup abc123 "what about applications in healthcare?"

        asta literature followup abc123 "only papers from 2024" --timeout 60
    """
    state = require_thread_state(thread_id)

    try:
        client = AstaPaperFinder(user_id=state.user_id or None)
        result = client.send_followup(thread_id, message, timeout=timeout)

        papers = result["widget"].get("results", [])
        response_text = result.get("response", "")
        prev_count = len(state.current_results)
        turn_number = len(state.turns) + 1

        turn = Turn(
            turn_number=turn_number,
            type="followup",
            input=message,
            timestamp=datetime.now(UTC).isoformat(),
            result_count=len(papers),
        )
        state = update_thread_turn(thread_id, turn, papers)

        # Save this turn's results as a separate file
        results_path = save_results(
            state.session_slug,
            turn_number,
            message,
            {"query": message, "response": response_text, "results": papers},
        )

        # Print agent response to stdout
        if response_text:
            click.echo(response_text)

        # Concise stdout
        click.echo(f"Thread {thread_id} updated (turn {turn_number})")
        click.echo(f'Message: "{message}"')
        click.echo(f"Papers: {len(papers)} (was {prev_count})")

        # Top 3 titles
        if papers:
            click.echo("Top hits:")
            for i, p in enumerate(papers[:3], 1):
                click.echo(format_paper_line(i, p))

        sess = session_dir(state.session_slug)
        click.echo(f"Session: {sess}", err=True)
        click.echo(f"Results: {results_path}", err=True)
        click.echo(f"Asta: {client.base_url}/share/{thread_id}", err=True)

    except TimeoutError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(2)
    except Exception as e:
        raise click.ClickException(str(e))
