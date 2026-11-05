"""`asta feedback` — submit feedback on Asta plugins and tools."""

import click

from asta.feedback.submit import submit as submit_cmd


@click.group()
def feedback():
    """Submit feedback on Asta plugins and tools.

    Populate a local directory with a FEEDBACK.md narrative and optional
    supporting reports, review it, then run `submit <dir>` to upload it for
    the Asta team to analyze. Auth comes from `asta auth login`.
    """
    pass


feedback.add_command(submit_cmd)
