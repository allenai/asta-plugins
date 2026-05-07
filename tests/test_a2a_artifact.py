"""Tests for the A2A artifact -> LiteratureSearchResult translator."""

from asta.literature.a2a_artifact import parse_artifact


def _sample_artifact() -> dict:
    """Mirror the wire shape produced by mabool's ``to_a2a_artifact``."""
    return {
        "id": "task-1",
        "name": "Paper Finder Results",
        "subtype": "paper-finder-search-result",
        "schemaVersion": "1",
        "description": "Found 2 relevant papers.",
        "entities": {
            "ent_001": {
                "id": "ent_001",
                "type": "PAPER",
                "displayLabel": "Attention Is All You Need",
                "s2Metadata": {
                    "title": "Attention Is All You Need",
                    "abstract": "We propose a new architecture...",
                    "year": 2017,
                    "venue": "NeurIPS",
                    "corpusId": "13756489",
                    "authors": [
                        {"name": "Ashish Vaswani", "authorId": "a-1"},
                        {"name": "Noam Shazeer", "authorId": "a-2"},
                    ],
                },
                "url": "https://www.semanticscholar.org/paper/13756489",
                "tldr": "The transformer architecture.",
                "relevanceScore": 0.92,
                "rerankScore": 0.84,
                "citationCount": 100000,
                "snippets": [
                    {
                        "text": "We propose...",
                        "sectionTitle": "Introduction",
                        "sectionKind": "body",
                        "charStartOffset": 0,
                        "charEndOffset": 12,
                    }
                ],
                "relevanceJudgement": {
                    "relevance": 3,
                    "score": 0.95,
                    "summary": "Foundational paper for the topic.",
                    "modelName": "asta-rj-1",
                    "criteria": [
                        {
                            "name": "introduces transformers",
                            "relevance": 3,
                            "snippets": [
                                {
                                    "text": "We propose a new architecture",
                                    "sectionTitle": "Abstract",
                                    "sectionKind": "abstract",
                                },
                                {
                                    "text": "Vaswani et al. (2017) introduce...",
                                    "sourceCorpusId": "999",
                                },
                            ],
                        }
                    ],
                },
            },
            "ent_002": {
                "id": "ent_002",
                "type": "PAPER",
                "displayLabel": "BERT",
                "s2Metadata": {
                    "title": "BERT: Pre-training of Deep Bidirectional Transformers",
                    "year": 2018,
                    "corpusId": "52967399",
                    "authors": [{"name": "Jacob Devlin", "authorId": "a-3"}],
                },
                "relevanceScore": 0.88,
            },
        },
        "annotations": {},
        "content": [],
    }


def test_translates_paper_entities():
    artifact = _sample_artifact()
    result = parse_artifact(
        artifact, query="transformers", thread_id="t-42", narrative="Done."
    )
    assert result.query == "transformers"
    assert result.thread_id == "t-42"
    assert result.narrative == "Done."
    assert len(result.results) == 2

    p1 = next(p for p in result.results if p.title.startswith("Attention"))
    assert p1.corpusId == 13756489  # coerced from string
    assert p1.year == 2017
    assert p1.venue == "NeurIPS"
    assert p1.url and "13756489" in p1.url
    assert p1.citationCount == 100000
    assert p1.relevanceScore == 0.92
    assert [a.name for a in p1.authors] == ["Ashish Vaswani", "Noam Shazeer"]
    assert p1.authors[0].id == "a-1"


def test_translates_renamed_relevance_judgement_fields():
    artifact = _sample_artifact()
    result = parse_artifact(artifact, query="q", thread_id=None, narrative=None)
    p1 = next(p for p in result.results if p.title.startswith("Attention"))
    rj = p1.relevanceJudgement
    assert rj is not None
    # `summary` -> `relevanceSummary`
    assert rj.relevanceSummary == "Foundational paper for the topic."
    # `criteria` -> `relevanceCriteriaJudgements`
    assert len(rj.relevanceCriteriaJudgements) == 1
    crit = rj.relevanceCriteriaJudgements[0]
    assert crit.name == "introduces transformers"
    # `snippets` (union of evidence + citation-context) -> drop citation contexts,
    # keep evidence snippets only
    assert len(crit.relevantSnippets) == 1
    assert crit.relevantSnippets[0].sectionTitle == "Abstract"


def test_thread_id_and_narrative_optional():
    artifact = _sample_artifact()
    result = parse_artifact(artifact, query="q", thread_id=None, narrative=None)
    assert result.thread_id is None
    assert result.narrative is None


def test_skips_non_paper_entities():
    artifact = _sample_artifact()
    artifact["entities"]["ent_999"] = {
        "id": "ent_999",
        "type": "AUTHOR",
        "displayLabel": "Some Author",
    }
    result = parse_artifact(artifact, query="q", thread_id=None, narrative=None)
    assert len(result.results) == 2  # AUTHOR entity ignored


def test_warns_on_unexpected_schema_version(capsys):
    artifact = _sample_artifact()
    artifact["schemaVersion"] = "2"
    parse_artifact(artifact, query="q", thread_id=None, narrative=None)
    captured = capsys.readouterr()
    assert "schemaVersion" in captured.err
