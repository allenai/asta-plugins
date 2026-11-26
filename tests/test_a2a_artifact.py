"""Tests for the A2A v4 artifacts -> LiteratureSearchResult translator and the
v4 paper adapter it shares with ``asta literature find``."""

from asta.literature.a2a_artifact import parse_artifacts
from asta.literature.v4_papers import v4_paper_to_paper
from tests._v4_fixtures import v4_paper, v4_search_result, v4_sparse_paper


def test_maps_full_v4_paper():
    paper = v4_paper_to_paper(v4_paper()).model_dump(mode="json")
    assert paper == {
        "corpusId": 13756489,
        "title": "Attention Is All You Need",
        "abstract": "We propose a new architecture...",
        "year": 2017,
        "authors": [
            {"name": "Ashish Vaswani", "id": "a-1"},
            {"name": "Noam Shazeer", "id": ""},
        ],
        "venue": "NeurIPS",
        "journal": {"name": "NeurIPS", "pages": "5998-6008"},
        "url": "https://www.semanticscholar.org/p/13756489",
        "publicationDate": "2017-06-12",
        "citationCount": 100000,
        "categories": [],
        "relevanceScore": 0.92,
        "relevanceJudgement": {
            "relevance": 3,
            "relevanceSummary": "Foundational paper for the topic.",
            "relevanceCriteriaJudgements": [
                {
                    "name": "introduces transformers",
                    "relevance": 3,
                    "relevantSnippets": [
                        {
                            "text": "a new architecture",
                            "sectionTitle": "Abstract",
                            "sentenceIds": [],
                        }
                    ],
                    "numOfOmittedRelevanceSnippetsDueLegal": 1,
                },
                {
                    "name": "attention only",
                    "relevance": 2,
                    "relevantSnippets": [],
                    "numOfOmittedRelevanceSnippetsDueLegal": 0,
                },
            ],
        },
        "snippets": [
            {"text": "We propose...", "sectionTitle": "Introduction", "sentenceIds": []}
        ],
        "citationContexts": [
            {
                "text": "the Transformer [12]",
                "sourceCorpusId": 999,
                "withinSnippetOffsetStart": None,
                "withinSnippetOffsetEnd": None,
                "sourceSentenceIds": [],
            },
            {
                "text": "as in [3]",
                "sourceCorpusId": None,
                "withinSnippetOffsetStart": None,
                "withinSnippetOffsetEnd": None,
                "sourceSentenceIds": [],
            },
        ],
        "legalToShow": True,
        "numOfOmittedCitationContextsDueLegal": 2,
    }


def test_maps_unjudged_paper_without_score_abstract_or_authors():
    paper = v4_paper_to_paper(v4_sparse_paper())
    assert paper.corpusId == 52967399
    assert paper.abstract is None
    assert paper.authors == []
    assert paper.relevanceScore is None
    assert paper.relevanceJudgement is None
    assert paper.snippets == []
    assert paper.legalToShow is False


def test_parse_artifacts_keeps_each_paper_once_in_artifact_order():
    artifacts = [
        v4_search_result([v4_paper(), v4_sparse_paper("1")], artifact_id="sr-1"),
        v4_search_result([v4_sparse_paper("2"), v4_paper()], artifact_id="sr-2"),
    ]
    result = parse_artifacts(
        artifacts, query="transformers", thread_id="t-42", narrative="Done."
    )
    assert (result.query, result.thread_id, result.narrative) == (
        "transformers",
        "t-42",
        "Done.",
    )
    assert [p.corpusId for p in result.results] == [13756489, 1, 2]


def test_warns_on_unexpected_kind_version(capsys):
    artifact = v4_search_result([v4_paper()])
    artifact["kindVersion"] = "5"
    result = parse_artifacts([artifact], query="q", thread_id=None, narrative=None)
    assert [p.corpusId for p in result.results] == [13756489]
    assert "kindVersion='5'" in capsys.readouterr().err
