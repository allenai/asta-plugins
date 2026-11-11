"""Paper Finder result v4 payloads in the ``full`` preset, as mabool's
``result_v4`` dumps them (camelCase, ``exclude_none``, string corpus ids)."""

from __future__ import annotations

from typing import Any


def v4_paper() -> dict[str, Any]:
    return {
        "corpusId": "13756489",
        "details": {
            "title": "Attention Is All You Need",
            "url": "https://www.semanticscholar.org/p/13756489",
            "authors": [
                {"name": "Ashish Vaswani", "authorId": "a-1"},
                {"name": "Noam Shazeer"},
            ],
            "citationCount": 100000,
            "year": 2017,
            "publicationDate": "2017-06-12",
            "venue": "NeurIPS",
            "journal": {"name": "NeurIPS", "pages": "5998-6008"},
            "abstract": "We propose a new architecture...",
        },
        "relevance": {
            "tier": 3,
            "score": 0.92,
            "judgementScore": 0.95,
            "summary": "Foundational paper for the topic.",
            "criteria": [
                {"name": "introduces transformers", "tier": 3},
                {"name": "attention only", "tier": 2},
            ],
        },
        "evidence": {
            "tldr": "The transformer architecture.",
            "snippets": [
                {
                    "text": "We propose...",
                    "sectionTitle": "Introduction",
                    "sectionKind": "body",
                }
            ],
            "criteria": [
                {
                    "name": "introduces transformers",
                    "snippets": [
                        {"text": "a new architecture", "sectionTitle": "Abstract"}
                    ],
                    "citationContexts": [
                        {"text": "Vaswani et al. introduce", "sourceCorpusId": "9"}
                    ],
                    "omitted": 1,
                }
            ],
            "citationContexts": [
                {"text": "the Transformer [12]", "sourceCorpusId": "999"},
                {"text": "as in [3]"},
            ],
            "legalToShow": True,
            "omitted": {
                "abstract": False,
                "snippets": 0,
                "criterionEvidence": 1,
                "citationContexts": 2,
            },
        },
    }


def v4_sparse_paper(corpus_id: str = "52967399") -> dict[str, Any]:
    """A paper that wasn't judged, has no authors or score, and isn't legal to show."""
    return {
        "corpusId": corpus_id,
        "details": {
            "title": "BERT",
            "url": f"https://www.semanticscholar.org/p/{corpus_id}",
            "authors": [],
            "citationCount": 0,
        },
        "relevance": {"tier": -1, "criteria": []},
        "evidence": {
            "snippets": [],
            "criteria": [],
            "citationContexts": [],
            "legalToShow": False,
            "omitted": {
                "abstract": True,
                "snippets": 2,
                "criterionEvidence": 0,
                "citationContexts": 0,
            },
        },
    }


def v4_search_result(
    papers: list[dict[str, Any]], artifact_id: str = "sr-1"
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "kind": "search-result",
        "kindVersion": "4",
        "name": "Papers on transformers",
        "papers": papers,
    }
