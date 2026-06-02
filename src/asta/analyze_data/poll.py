"""`asta analyze-data poll` — block until a task reaches a terminal state.

Replaces the inline bash polling loop that previously lived in the
analyze-data skill body. Status ticks go to stderr; the final Task JSON
goes to ``--output`` (or stdout) so the harness's background-task log
shows progress without polluting the captured payload.

Delegates the actual polling + rendering to the shared
``asta_agent.a2a.commands._poll_until_terminal``, so step-progress
events, parent/child indent, elapsed times, and artifact lines all
surface here — the previous bespoke loop only emitted ``state=...``
ticks (and one per poll, even when nothing changed).
"""

from __future__ import annotations

import json

import click
from asta_agent.a2a.client import A2AClient
from asta_agent.a2a.commands import _poll_until_terminal

from asta.analyze_data._url import dv_url
from asta.utils.auth_helper import get_access_token


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
    default=None,
    type=click.IntRange(min=1),
    help="Seconds between polls. Omit for the SDK's adaptive cadence "
         "(5×6 then 15×20 then 60s).",
)
def poll(task_id: str, output: str | None, interval: int | None) -> None:
    """Poll TASK_ID until it reaches a terminal state, then emit the final Task JSON.

    Terminal states: completed, failed, input-required, canceled, rejected, auth-required.
    Progress lines ([HH:MM:SS] state=…, step labels, artifacts) go to stderr;
    the final Task JSON goes to --output (or stdout).
    """
    client = A2AClient(dv_url(), api_key=get_access_token())
    final = _poll_until_terminal(client, task_id, interval=interval)
    payload = json.dumps(final, indent=2)
    if output:
        with open(output, "w") as f:
            f.write(payload)
    else:
        click.echo(payload)
