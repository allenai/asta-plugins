"""`asta analyze-data poll` — block until a task reaches a terminal state.

Replaces the inline bash polling loop that previously lived in the
analyze-data skill body. Status ticks go to stderr; the final Task JSON
goes to ``--output`` (or stdout) so the harness's background-task log
shows progress without polluting the captured payload.
"""

from __future__ import annotations

import time
from datetime import datetime

import click
from a2a.types import Task, TaskState

from asta.analyze_data._url import dv_url
from asta.utils.auth_helper import get_access_token
from asta_agent.a2a.client import A2AClient, A2AError

_TERMINAL_STATES = {
    TaskState.completed,
    TaskState.failed,
    TaskState.input_required,
    TaskState.canceled,
    TaskState.rejected,
    TaskState.auth_required,
}


@click.command()
@click.argument("task_id")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write final task JSON to PATH (default: stdout).",
)
@click.option(
    "--interval",
    default=60,
    show_default=True,
    type=click.IntRange(min=1),
    help="Seconds between polls.",
)
def poll(task_id: str, output: str | None, interval: int) -> None:
    """Poll TASK_ID until it reaches a terminal state, then emit the final Task JSON.

    Terminal states: completed, failed, input-required, canceled, rejected, auth-required.
    Status ticks ([HH:MM:SS] state=...) are written to stderr; transient errors
    are logged and retried.
    """
    client = A2AClient(dv_url(), api_key=get_access_token())

    while True:
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            result = client.get_task(task_id)
            parsed = Task.model_validate(result)
        except A2AError as e:
            click.echo(f"[{ts}] error: {e.code} {e}", err=True)
            time.sleep(interval)
            continue
        except Exception as e:
            click.echo(f"[{ts}] error: {e}", err=True)
            time.sleep(interval)
            continue

        state = parsed.status.state
        click.echo(f"[{ts}] state={state.value}", err=True)

        if state in _TERMINAL_STATES:
            payload = parsed.model_dump_json(by_alias=True, indent=2, exclude_none=True)
            if output:
                with open(output, "w") as f:
                    f.write(payload)
            else:
                click.echo(payload)
            return

        time.sleep(interval)
