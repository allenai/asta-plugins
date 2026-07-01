"""Snowball papers command"""

import json
from pathlib import Path

import click

from asta.literature.client import AstaPaperFinder
from asta.literature.models import LiteratureSearchResult


def _parse_seed(spec: str) -> dict:
    """Parse a ``corpusId:relevance`` seed spec into a seed dict.

    ``relevance`` is optional and defaults to 3. Examples: ``280012121:3``,
    ``280012121`` (relevance defaults to 3).
    """
    corpus_id, sep, rel = spec.partition(":")
    corpus_id = corpus_id.strip()
    if not corpus_id:
        raise click.BadParameter(f"seed '{spec}' is missing a corpus id")
    if sep:
        try:
            relevance = int(rel.strip())
        except ValueError:
            raise click.BadParameter(
                f"seed '{spec}' has a non-integer relevance '{rel}'"
            )
    else:
        relevance = 3
    if not (-1 <= relevance <= 3):
        raise click.BadParameter(
            f"seed '{spec}' relevance must be in [-1, 3], got {relevance}"
        )
    return {"corpus_id": corpus_id, "relevance": relevance}


def _load_seeds_file(path: str) -> list[dict]:
    """Load seeds from a JSON file.

    Accepts either a list of seed objects (``[{"corpus_id": ..., "relevance": ...}]``)
    or a list of ``"corpusId:relevance"`` strings.
    """
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise click.BadParameter(f"--seeds-file must contain a JSON list, got {type(data).__name__}")
    seeds: list[dict] = []
    for item in data:
        if isinstance(item, str):
            seeds.append(_parse_seed(item))
        elif isinstance(item, dict) and "corpus_id" in item:
            seeds.append(
                {
                    "corpus_id": str(item["corpus_id"]),
                    "relevance": int(item.get("relevance", 3)),
                }
            )
        else:
            raise click.BadParameter(f"unrecognized seed entry: {item!r}")
    return seeds


@click.command()
@click.option(
    "--mode",
    type=click.Choice(["backward", "forward", "citances"]),
    default="backward",
    help="Mode: backward (references), forward (citations), citances (snippet-derived, needs --query).",
)
@click.option(
    "--seed",
    "seeds",
    multiple=True,
    metavar="CORPUSID[:RELEVANCE]",
    help="A seed paper as corpusId:relevance (relevance 0-3, default 3). Repeatable.",
)
@click.option(
    "--seeds-file",
    type=click.Path(exists=True),
    help="JSON file with a list of seeds (objects or 'corpusId:relevance' strings).",
)
@click.option(
    "--query",
    default=None,
    help="Search query. Required for --mode citances.",
)
@click.option(
    "--top-k",
    type=int,
    default=None,
    help="Number of candidates to promote (maps to backward/forward top_k per mode).",
)
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
def snowball(
    mode: str,
    seeds: tuple[str, ...],
    seeds_file: str | None,
    query: str | None,
    top_k: int | None,
    output: str,
    timeout: int,
):
    """Snowball from SEED papers via citation graph using Asta Paper Finder.

    Provide seeds with repeated --seed corpusId:relevance and/or a --seeds-file.
    Requires an output file path to save results.

    Examples:

        # Backward snowball (references of the seeds)
        asta literature snowball --mode backward --seed 280012121:3 --top-k 5 -o out.json

        # Multiple seeds
        asta literature snowball --seed 280012121:3 --seed 12345:2 -o out.json

        # From a seeds file
        asta literature snowball --seeds-file seeds.json -o out.json

        # Citances mode (query required)
        asta literature snowball --mode citances --query "graph neural networks" \\
          --seed 280012121:3 -o out.json
    """
    try:
        seed_list: list[dict] = [_parse_seed(s) for s in seeds]
        if seeds_file:
            seed_list.extend(_load_seeds_file(seeds_file))
        if not seed_list:
            raise click.UsageError("At least one seed is required (use --seed or --seeds-file)")

        # Map --top-k to the relevant per-mode parameter.
        backward_top_k = top_k if mode == "backward" else None
        forward_top_k = top_k if mode == "forward" else None
        snippet_top_k = top_k if mode == "citances" else None

        client = AstaPaperFinder()
        raw_result = client.snowball(
            mode=mode,
            seeds=seed_list,
            query=query,
            forward_top_k=forward_top_k,
            backward_top_k=backward_top_k,
            snippet_top_k=snippet_top_k,
            timeout=timeout,
            save_to_file=None,
        )

        # Transform to literature search result format (mirrors `find`).
        literature_result = LiteratureSearchResult(
            query=raw_result["query"],
            results=raw_result["widget"]["results"],
            narrative=raw_result["widget"].get("response_text") or None,
        )

        output_data = literature_result.model_dump(mode="json", exclude_none=False)

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2)

        click.echo(
            f"Snowball ({mode}) found {len(literature_result.results)} papers. "
            f"Results saved to: {output_path}",
            err=True,
        )

    except TimeoutError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(2)
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(str(e))
