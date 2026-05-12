"""Get paper details command"""

import json
import os
from calendar import monthrange
from datetime import datetime

import click

from asta.papers.client import SemanticScholarClient

# Matches astabench MCP's error verbatim:
# https://github.com/allenai/asta-bench/blob/4f0a846/astabench/tools/asta_tools.py#L244-L247
_CUTOFF_MESSAGE_TEMPLATE = (
    "Paper {paper_id!r} is newer than the date cutoff of {cutoff} "
    "and is not allowed to be requested"
)


@click.command()
@click.argument("paper_id")
@click.option(
    "--fields",
    default="title,abstract,authors,year,venue,citationCount,publicationDate,url",
    help="Comma-separated fields to return",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def get(paper_id: str, fields: str, output_format: str):
    """Get details for a paper by ID.

    PAPER_ID can be:
    - CorpusId:215416146
    - DOI:10.18653/v1/N18-3011
    - ARXIV:2106.15928
    - PMID:19872477
    - URL:https://arxiv.org/abs/2106.15928

    Examples:

        asta papers get ARXIV:2005.14165

        asta papers get "DOI:10.18653/v1/N18-3011" --fields title,year,authors
    """
    try:
        cutoff = _upper_bound(os.environ.get("ASTA_PUBLICATION_DATE_RANGE"))
        effective_fields = _ensure_date_fields(fields) if cutoff else fields

        client = SemanticScholarClient()
        result = client.get_paper(paper_id, fields=effective_fields)

        if cutoff is not None:
            paper_date = _paper_date(result)
            if paper_date is None or paper_date > cutoff:
                raise click.ClickException(
                    _CUTOFF_MESSAGE_TEMPLATE.format(
                        paper_id=paper_id, cutoff=cutoff.strftime("%Y-%m-%d")
                    )
                )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            # Text format
            click.echo(f"Title: {result.get('title', 'N/A')}")
            click.echo(f"Year: {result.get('year', 'N/A')}")
            if authors := result.get("authors"):
                author_names = ", ".join(a["name"] for a in authors[:5])
                if len(authors) > 5:
                    author_names += f", et al. ({len(authors)} total)"
                click.echo(f"Authors: {author_names}")
            click.echo(f"Venue: {result.get('venue', 'N/A')}")
            click.echo(f"Citations: {result.get('citationCount', 0)}")
            if abstract := result.get("abstract"):
                click.echo(f"\nAbstract: {abstract}")
            if url := result.get("url"):
                click.echo(f"\nURL: {url}")

    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(str(e))


def _upper_bound(date_range: str | None) -> datetime | None:
    """Inclusive upper-bound datetime extracted from an S2
    ``publicationDateOrYear`` value, or ``None`` if the value is unset
    or open-ended on the right.

    Forms (per S2's ``publicationDateOrYear`` syntax):
      - ``":2024-10-17"`` / ``"2020:2024-10-17"`` → upper = 2024-10-17
      - ``"2020-2024"``                          → upper = end of 2024
      - ``"2020-"`` / ``":"``                    → no upper bound
      - ``"2020"`` / ``"2024-01-15"``            → upper = end of period
    """
    if not date_range:
        return None
    if ":" in date_range:
        upper = date_range.split(":", 1)[1]
    elif _is_year_range(date_range):
        upper = date_range.split("-", 1)[1]
    else:
        upper = date_range
    return _end_of_period(upper) if upper else None


def _is_year_range(s: str) -> bool:
    parts = s.split("-")
    return (
        len(parts) == 2
        and len(parts[0]) == 4
        and parts[0].isdigit()
        and (not parts[1] or (len(parts[1]) == 4 and parts[1].isdigit()))
    )


def _end_of_period(s: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            d = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if fmt == "%Y":
            return datetime(d.year, 12, 31)
        if fmt == "%Y-%m":
            return datetime(d.year, d.month, monthrange(d.year, d.month)[1])
        return d
    raise click.ClickException(
        f"ASTA_PUBLICATION_DATE_RANGE: cannot parse {s!r} (expected YYYY, "
        f"YYYY-MM, or YYYY-MM-DD)"
    )


def _paper_date(paper: dict) -> datetime | None:
    """Best-effort publication date with year fallback. Mirrors the
    approximation used in astabench's ``_filter_one_paper``: when the
    response only carries ``year``, treat it as the last day of that
    year so a strict ``:YYYY-12-31`` cutoff still admits the paper."""
    if pub := paper.get("publicationDate"):
        try:
            return datetime.strptime(pub, "%Y-%m-%d")
        except ValueError:
            pass
    if year := paper.get("year"):
        return datetime(int(year), 12, 31)
    return None


def _ensure_date_fields(fields: str) -> str:
    """Force the response to include the fields needed for cutoff
    enforcement, even if the caller asked for a narrower set."""
    parts = [f.strip() for f in fields.split(",") if f.strip()]
    for needed in ("publicationDate", "year"):
        if needed not in parts:
            parts.append(needed)
    return ",".join(parts)
