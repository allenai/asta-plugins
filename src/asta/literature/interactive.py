"""``asta literature interactive`` — paper-finder skill on top of the generic
A2A interactive runner.
"""

import click

from asta.literature.a2a_artifact import parse_artifact
from asta.literature.models import LiteratureSearchResult
from asta.utils.a2a_interactive import (
    A2ASkillSpec,
    run_a2a_session,
    standard_a2a_options,
)

PAPER_FINDER_SPEC = A2ASkillSpec(
    config_key="paper_finder",
    env_var="ASTA_PAPER_FINDER_A2A_URL",
)


@click.command()
@click.argument("query")
@click.option(
    "--mode",
    type=click.Choice(["infer", "fast", "diligent"]),
    default="infer",
    help="Search strategy: infer (auto-detect), fast (quick), or diligent (comprehensive)",
)
@standard_a2a_options
def interactive(
    query: str,
    mode: str,
    output: str,
    thread_dir: str | None,
    timeout: int,
    server: str | None,
    api_key: str | None,
):
    """Conduct a stateful, multi-turn literature search via the Asta Paper Finder A2A endpoint.

    Conversation continuation is via ``--thread-dir DIR``: every turn writes
    its artifact under DIR with a turn-index suffix (DIR/<-o stem>.NNN.<ext>)
    and updates DIR/index.json. Subsequent invocations against the same DIR
    auto-resume the conversation's thread_id from the index. Without
    ``--thread-dir`` an invocation is a one-shot turn that doesn't continue
    any prior conversation.

    Output schema mirrors `asta literature find` (LiteratureSearchResult), with
    additional `thread_id` and `narrative` fields.

    Examples:

        # One-shot turn, no continuation
        asta literature interactive "transformer architecture survey" -o /tmp/r.json

        # Persisted multi-turn session (recommended for exploratory work).
        # Convention: .asta/literature/threads/<YYYY-MM-DD>-<slug>/
        asta literature interactive "transformer architecture survey" \\
          --thread-dir .asta/literature/threads/2026-05-04-transformer-architectures \\
          -o transformer-survey.json
        asta literature interactive "narrow to 2023+ surveys" \\
          --thread-dir .asta/literature/threads/2026-05-04-transformer-architectures \\
          -o narrow-2023.json
        # → DIR/transformer-survey.001.json, DIR/narrow-2023.002.json, DIR/index.json

        # Local mabool dev server (no auth — the gateway handles it in prod)
        asta literature interactive "deep learning" \\
          --server http://localhost:8000 -o /tmp/r.json
    """
    run_a2a_session(
        PAPER_FINDER_SPEC,
        output=output,
        thread_dir=thread_dir,
        timeout=timeout,
        server=server,
        api_key=api_key,
        message_data={"query": query, "operation_mode": mode},
        artifact_to_result=lambda artifact, ctx_thread_id, narrative: parse_artifact(
            artifact,
            query=query,
            thread_id=ctx_thread_id,
            narrative=narrative,
        ),
        build_summary=lambda result, narrative: _build_summary(
            result, narrative, mode=mode
        ),
    )


def _build_summary(
    result: LiteratureSearchResult, narrative: str | None, *, mode: str
) -> dict:
    """Per-turn metadata recorded under ``summary`` in ``DIR/index.json``."""
    return {
        "query": result.query,
        "mode": mode,
        "narrative": narrative,
        "paper_count": len(result.results),
    }
