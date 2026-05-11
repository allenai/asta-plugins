"""Translate the A2A ``paper-finder-search-result`` artifact into ``LiteratureSearchResult``.

The artifact wire format (mabool's ``artifact_translator.py``) uses the asta
envelope plus paper-finder-specific extension fields and rename mappings:
``relevanceJudgement.summary`` (vs. our ``relevanceSummary``),
``relevanceJudgement.criteria`` (vs. ``relevanceCriteriaJudgements``),
``criteria[].snippets`` (vs. ``relevantSnippets``). This module bridges that.
"""

import sys
from typing import Any

from asta.literature.models import (
    Author,
    LiteratureSearchResult,
    Paper,
    RelevanceCriteriaJudgement,
    RelevanceJudgement,
    RelevantSnippet,
    Snippet,
)

EXPECTED_SCHEMA_VERSION = "1"


def parse_artifact(
    artifact: dict[str, Any],
    *,
    query: str,
    thread_id: str | None,
    narrative: str | None,
) -> LiteratureSearchResult:
    """Convert a ``paper-finder-search-result`` artifact dict into ``LiteratureSearchResult``.

    Acceptable gaps vs. the headless ``find`` path: ``citationContexts``,
    ``publicationDate``, ``categories``, ``journal`` are not emitted by the
    A2A translator and will be empty/None in the result.
    """
    schema_version = artifact.get("schemaVersion")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        print(
            f"warning: unexpected paper-finder artifact schemaVersion={schema_version!r} "
            f"(expected {EXPECTED_SCHEMA_VERSION!r}); proceeding best-effort",
            file=sys.stderr,
        )

    papers: list[Paper] = []
    for entity in (artifact.get("entities") or {}).values():
        if entity.get("type") != "PAPER":
            continue
        papers.append(_paper_from_entity(entity))

    return LiteratureSearchResult(
        query=query,
        results=papers,
        thread_id=thread_id,
        narrative=narrative,
    )


def _paper_from_entity(entity: dict[str, Any]) -> Paper:
    s2 = entity.get("s2Metadata") or {}
    authors = [
        Author(name=a.get("name", ""), id=a.get("authorId") or "")
        for a in (s2.get("authors") or [])
    ]
    snippets = [
        Snippet(text=s.get("text", ""), sectionTitle=s.get("sectionTitle"))
        for s in (entity.get("snippets") or [])
    ]
    return Paper(
        corpusId=s2.get("corpusId"),
        title=s2.get("title", "") or "",
        abstract=s2.get("abstract"),
        year=s2.get("year"),
        venue=s2.get("venue"),
        authors=authors,
        url=entity.get("url"),
        citationCount=entity.get("citationCount"),
        relevanceScore=entity.get("relevanceScore", 0.0),
        relevanceJudgement=_parse_relevance_judgement(entity.get("relevanceJudgement")),
        snippets=snippets,
    )


def _parse_relevance_judgement(rj: dict[str, Any] | None) -> RelevanceJudgement | None:
    if not rj:
        return None
    criteria_payloads = rj.get("criteria") or []
    criteria: list[RelevanceCriteriaJudgement] = []
    for c in criteria_payloads:
        # criteria[].snippets is a union of evidence-snippet (has sectionTitle)
        # and citation-context (has sourceCorpusId). Keep evidence snippets;
        # drop citation contexts — they don't fit RelevantSnippet's shape.
        relevant_snippets = [
            RelevantSnippet(text=s.get("text", ""), sectionTitle=s.get("sectionTitle"))
            for s in (c.get("snippets") or [])
            if "sourceCorpusId" not in s
        ]
        criteria.append(
            RelevanceCriteriaJudgement(
                name=c.get("name", "") or "",
                relevance=c.get("relevance", 0) or 0,
                relevantSnippets=relevant_snippets,
            )
        )
    return RelevanceJudgement(
        relevance=rj.get("relevance", 0) or 0,
        relevanceSummary=rj.get("summary", "") or "",
        relevanceCriteriaJudgements=criteria,
    )
