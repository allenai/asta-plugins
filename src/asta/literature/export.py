"""Export thread results to various formats."""

import csv
import io
import json

import click

from asta.literature.threads import require_thread_state, session_dir


def _to_bibtex(papers: list) -> str:
    entries = []
    for p in papers:
        authors_list = p.get("authors", [])
        author_str = " and ".join(a.get("name", "") for a in authors_list)
        year = p.get("year", "")
        corpus_id = p.get("corpusId", "unknown")
        key = f"s2:{corpus_id}"
        title = p.get("title", "")
        venue = p.get("venue", "")

        entry = (
            f"@article{{{key},\n"
            f"  title = {{{title}}},\n"
            f"  author = {{{author_str}}},\n"
            f"  year = {{{year}}},\n"
            f"  journal = {{{venue}}},\n"
            f"}}"
        )
        entries.append(entry)
    return "\n\n".join(entries)


def _to_csv(papers: list) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "corpusId",
            "title",
            "year",
            "authors",
            "venue",
            "citationCount",
            "relevanceScore",
        ]
    )
    for p in papers:
        authors_list = p.get("authors", [])
        author_str = "; ".join(a.get("name", "") for a in authors_list)
        writer.writerow(
            [
                p.get("corpusId", ""),
                p.get("title", ""),
                p.get("year", ""),
                author_str,
                p.get("venue", ""),
                p.get("citationCount", ""),
                p.get("relevanceScore", ""),
            ]
        )
    return output.getvalue()


@click.command()
@click.argument("thread_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "bibtex", "csv"]),
    default="json",
    help="Export format (default: json)",
)
def export(thread_id: str, fmt: str):
    """Export thread results to the session folder.

    Writes to the session's exports/ subdirectory.

    Examples:

        asta literature export abc123 --format json

        asta literature export abc123 --format bibtex

        asta literature export abc123 --format csv
    """
    state = require_thread_state(thread_id)

    sess = session_dir(state.session_slug)
    exports_dir = sess / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    papers = state.current_results

    if fmt == "json":
        ext = "json"
        content = json.dumps(papers, indent=2)
    elif fmt == "bibtex":
        ext = "bib"
        content = _to_bibtex(papers)
    else:
        ext = "csv"
        content = _to_csv(papers)

    out_path = exports_dir / f"results.{ext}"
    with open(out_path, "w") as f:
        f.write(content)

    click.echo(f"Exported {len(papers)} papers to: {out_path}")
    click.echo(f"Session: {sess}", err=True)
