"""Paper Finder's result v4 papers as the plugin's ``Paper``.

Both ``asta literature find`` (REST) and ``asta literature interactive`` (A2A)
ask for the ``full`` preset, so every paper carries its ``details``,
``relevance`` and ``evidence`` layers. Fields the v4 schema makes optional are
read with ``.get``; required ones are indexed.
"""

from collections.abc import Iterable
from typing import Any

from asta.literature.models import (
    Author,
    CitationContext,
    Paper,
    RelevanceCriteriaJudgement,
    RelevanceJudgement,
    RelevantSnippet,
    Snippet,
)


def papers_of(artifacts: Iterable[dict[str, Any]]) -> list[Paper]:
    """The papers of every artifact in order; a paper in several artifacts is kept once."""
    papers: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        for paper in artifact["papers"]:
            papers.setdefault(paper["corpusId"], paper)
    return [v4_paper_to_paper(paper) for paper in papers.values()]


def v4_paper_to_paper(paper: dict[str, Any]) -> Paper:
    details = paper["details"]
    relevance = paper["relevance"]
    evidence = paper["evidence"]
    return Paper(
        corpusId=int(paper["corpusId"]),
        title=details["title"],
        abstract=details.get("abstract"),
        year=details.get("year"),
        authors=[
            Author(name=author["name"], id=author.get("authorId") or "")
            for author in details["authors"]
        ],
        venue=details.get("venue"),
        journal=details.get("journal"),
        url=details["url"],
        publicationDate=details.get("publicationDate"),
        citationCount=details["citationCount"],
        relevanceScore=relevance.get("score"),
        relevanceJudgement=_judgement(relevance, evidence),
        snippets=[
            Snippet(text=s["text"], sectionTitle=s.get("sectionTitle"))
            for s in evidence.get("snippets", [])
        ],
        citationContexts=[
            CitationContext(text=c["text"], sourceCorpusId=c.get("sourceCorpusId"))
            for c in evidence.get("citationContexts", [])
        ],
        legalToShow=evidence["legalToShow"],
        numOfOmittedCitationContextsDueLegal=evidence.get("omitted", {}).get(
            "citationContexts", 0
        ),
    )


def _judgement(
    relevance: dict[str, Any], evidence: dict[str, Any]
) -> RelevanceJudgement | None:
    """``None`` for a paper that wasn't judged (tier -1)."""
    if relevance["tier"] < 0:
        return None
    criterion_evidence = {c["name"]: c for c in evidence.get("criteria", [])}
    return RelevanceJudgement(
        relevance=relevance["tier"],
        relevanceSummary=relevance.get("summary", ""),
        relevanceCriteriaJudgements=[
            _criterion(c, criterion_evidence.get(c["name"], {}))
            for c in relevance.get("criteria", [])
        ],
    )


def _criterion(
    criterion: dict[str, Any], evidence: dict[str, Any]
) -> RelevanceCriteriaJudgement:
    return RelevanceCriteriaJudgement(
        name=criterion["name"],
        relevance=criterion["tier"],
        relevantSnippets=[
            RelevantSnippet(text=s["text"], sectionTitle=s.get("sectionTitle"))
            for s in evidence.get("snippets", [])
        ],
        numOfOmittedRelevanceSnippetsDueLegal=evidence.get("omitted", 0),
    )
