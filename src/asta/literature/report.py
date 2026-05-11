"""Generate literature report command"""

import json
from pathlib import Path

import click

from asta.literature.models import LiteratureSearchResult
from asta.literature.report_client import NoraReportClient


def _papers_to_documents(papers: list, max_papers: int) -> list[dict]:
    """Convert Paper model instances to the Document dicts expected by the API."""
    sorted_papers = sorted(papers, key=lambda p: p.relevanceScore, reverse=True)
    selected = sorted_papers[:max_papers]

    documents = []
    for paper in selected:
        doc: dict = {
            "corpus_id": str(paper.corpusId),
            "title": paper.title,
            "abstract": paper.abstract or "",
            "authors": [{"name": a.name} for a in paper.authors],
            "snippets": [
                {"text": s.text, "section_title": s.sectionTitle}
                for s in paper.snippets
            ],
            "year": paper.year,
            "venue": paper.venue,
            "relevance_judgement": paper.relevanceScore,
            "final_agent_score": paper.relevanceScore,
            "citation_count": paper.citationCount,
        }
        documents.append(doc)

    return documents


def _format_report(response: dict, query: str) -> str:
    """Render a TaskResult as a markdown document."""
    title = response.get("report_title") or query or "Literature Report"
    sections = response.get("sections", [])

    lines: list[str] = [f"# {title}", ""]
    for section in sections:
        if section.get("title"):
            lines.append(f"## {section['title']}")
            lines.append("")
        if section.get("text"):
            lines.append(section["text"])
            lines.append("")

    return "\n".join(lines)


@click.command()
@click.option(
    "-i",
    "--input",
    "input_file",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    help="Paper-finder results JSON file (from 'asta literature find')",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False),
    required=True,
    help="Output file path for the generated report (markdown)",
)
@click.option(
    "--query",
    default=None,
    help="Override the research query (defaults to the query stored in the results file)",
)
@click.option(
    "--max-papers",
    type=int,
    default=20,
    show_default=True,
    help="Maximum number of papers to include (highest-relevance first)",
)
def report(
    input_file: str,
    output: str,
    query: str | None,
    max_papers: int,
):
    """Generate a literature report from paper-finder results.

    Reads a results file produced by 'asta literature find', sends the papers
    to the Nora report generation API, and writes a markdown summary.

    Examples:

        # Generate report from an existing results file
        asta literature report -i results.json -o report.md

        # Override the query used as the report title/framing
        asta literature report -i results.json -o report.md --query "transformers for NLP"

        # Include more papers
        asta literature report -i results.json -o report.md --max-papers 30
    """
    try:
        with open(input_file) as f:
            raw = json.load(f)

        search_result = LiteratureSearchResult.model_validate(raw)
        effective_query = query or search_result.query

        click.echo(
            f"Loaded {len(search_result.results)} papers from {input_file}", err=True
        )

        documents = _papers_to_documents(search_result.results, max_papers)
        click.echo(f"Sending {len(documents)} papers to report API…", err=True)

        client = NoraReportClient()
        response = client.generate_report(documents=documents, query=effective_query)

        markdown = _format_report(response, effective_query)

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown)

        click.echo(f"Report saved to: {output_path}", err=True)

    except Exception as e:
        raise click.ClickException(str(e))
