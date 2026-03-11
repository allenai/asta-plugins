"""Tests for literature models"""

import json

from asta.literature.models import (
    Author,
    CitationContext,
    LiteratureSearchResult,
    Paper,
    RelevanceCriteriaJudgement,
    RelevanceJudgement,
    RelevantSnippet,
    Snippet,
)


class TestAuthor:
    """Test Author model"""

    def test_author_basic(self):
        """Test basic author creation"""
        author = Author(name="Alice Smith", id="123")
        assert author.name == "Alice Smith"
        assert author.id == "123"

    def test_author_with_alias(self):
        """Test author creation with authorId alias"""
        data = {"name": "Bob Jones", "authorId": "456"}
        author = Author(**data)
        assert author.name == "Bob Jones"
        assert author.id == "456"


class TestPaper:
    """Test Paper model"""

    def test_paper_minimal(self):
        """Test paper with minimal required fields"""
        paper = Paper(corpusId=123, title="Test Paper", relevanceScore=0.9)
        assert paper.corpusId == 123
        assert paper.title == "Test Paper"
        assert paper.relevanceScore == 0.9
        assert paper.authors == []
        assert paper.snippets == []

    def test_paper_snake_case_fields(self):
        """Test paper creation with snake_case field names (API format)"""
        data = {
            "corpus_id": 12345,
            "title": "Test Paper",
            "relevance_score": 0.95,
            "publication_date": "2024-01-15",
            "citation_count": 42,
        }
        paper = Paper(**data)
        assert paper.corpusId == 12345
        assert paper.relevanceScore == 0.95
        assert paper.publicationDate == "2024-01-15"
        assert paper.citationCount == 42

    def test_paper_string_authors_conversion(self):
        """Test automatic conversion of string authors to Author objects"""
        data = {
            "corpus_id": 12345,
            "title": "Test Paper",
            "relevance_score": 0.95,
            "authors": ["Alice Smith", "Bob Jones", "Charlie Brown"],
        }
        paper = Paper(**data)
        assert len(paper.authors) == 3
        assert isinstance(paper.authors[0], Author)
        assert paper.authors[0].name == "Alice Smith"
        assert paper.authors[0].id == ""
        assert paper.authors[1].name == "Bob Jones"
        assert paper.authors[2].name == "Charlie Brown"

    def test_paper_complete(self):
        """Test paper with all fields"""
        paper = Paper(
            corpusId=12345,
            title="Complete Paper",
            abstract="This is an abstract",
            year=2024,
            venue="NeurIPS",
            url="https://example.com",
            citationCount=42,
            relevanceScore=0.95,
            authors=[Author(name="Alice", id="1")],
            relevanceJudgement=RelevanceJudgement(
                relevance=3,
                relevanceSummary="Very relevant",
                relevanceCriteriaJudgements=[],
            ),
            snippets=[Snippet(text="Sample text", sectionTitle="Introduction")],
            citationContexts=[
                CitationContext(text="Citation text", sourceCorpusId=999)
            ],
        )

        assert paper.corpusId == 12345
        assert paper.year == 2024
        assert len(paper.authors) == 1
        assert paper.relevanceJudgement.relevanceSummary == "Very relevant"


class TestLiteratureSearchResult:
    """Test LiteratureSearchResult model"""

    def test_empty_results(self):
        """Test with no results"""
        result = LiteratureSearchResult(query="test query", results=[])
        assert result.query == "test query"
        assert result.results == []

    def test_with_results(self):
        """Test with paper results"""
        papers = [
            Paper(corpusId=1, title="Paper 1", relevanceScore=0.9),
            Paper(corpusId=2, title="Paper 2", relevanceScore=0.8),
        ]
        result = LiteratureSearchResult(query="machine learning", results=papers)

        assert result.query == "machine learning"
        assert len(result.results) == 2
        assert result.results[0].corpusId == 1
        assert result.results[1].title == "Paper 2"

    def test_serialization(self):
        """Test JSON serialization"""
        result = LiteratureSearchResult(
            query="test",
            results=[
                Paper(
                    corpusId=123,
                    title="Test",
                    relevanceScore=0.5,
                    authors=[Author(name="Alice", id="1")],
                )
            ],
        )

        # Serialize to dict
        data = result.model_dump(mode="json")
        assert data["query"] == "test"
        assert len(data["results"]) == 1
        assert data["results"][0]["corpusId"] == 123
        assert data["results"][0]["authors"][0]["name"] == "Alice"

        # Can be serialized to JSON
        json_str = json.dumps(data)
        assert "test" in json_str

    def test_from_api_response(self):
        """Test parsing from API response structure"""
        api_response = {
            "query": "transformers",
            "widget": {
                "results": [
                    {
                        "corpusId": 999,
                        "title": "Attention Is All You Need",
                        "abstract": "The dominant sequence transduction models...",
                        "year": 2017,
                        "authors": [{"name": "Ashish Vaswani", "authorId": "39570204"}],
                        "venue": "NeurIPS",
                        "relevanceScore": 0.99,
                        "relevanceJudgement": {
                            "relevance": 3,
                            "relevanceSummary": "Highly relevant",
                            "relevanceCriteriaJudgements": [],
                        },
                        "snippets": [],
                        "citationContexts": [],
                        "legalToShow": True,
                        "numOfOmittedCitationContextsDueLegal": 0,
                    }
                ]
            },
        }

        # Transform to LiteratureSearchResult
        result = LiteratureSearchResult(
            query=api_response["query"], results=api_response["widget"]["results"]
        )

        assert result.query == "transformers"
        assert len(result.results) == 1
        paper = result.results[0]
        assert paper.corpusId == 999
        assert paper.title == "Attention Is All You Need"
        assert paper.year == 2017
        assert paper.relevanceScore == 0.99
        assert len(paper.authors) == 1
        assert paper.authors[0].name == "Ashish Vaswani"


class TestRelevanceModels:
    """Test relevance-related models"""

    def test_relevant_snippet(self):
        """Test RelevantSnippet model"""
        snippet = RelevantSnippet(
            text="Sample text", sectionTitle="Methods", sentenceIds=["id1", "id2"]
        )
        assert snippet.text == "Sample text"
        assert snippet.sectionTitle == "Methods"
        assert len(snippet.sentenceIds) == 2

    def test_relevance_criteria_judgement(self):
        """Test RelevanceCriteriaJudgement model"""
        judgement = RelevanceCriteriaJudgement(
            name="Memory Systems",
            relevance=3,
            relevantSnippets=[
                RelevantSnippet(text="Evidence text", sectionTitle="Introduction")
            ],
        )
        assert judgement.name == "Memory Systems"
        assert judgement.relevance == 3
        assert len(judgement.relevantSnippets) == 1

    def test_relevance_judgement(self):
        """Test RelevanceJudgement model"""
        judgement = RelevanceJudgement(
            relevance=3,
            relevanceSummary="This paper discusses memory systems",
            relevanceCriteriaJudgements=[
                RelevanceCriteriaJudgement(
                    name="Long-term Memory", relevance=3, relevantSnippets=[]
                )
            ],
        )
        assert judgement.relevance == 3
        assert "memory systems" in judgement.relevanceSummary
        assert len(judgement.relevanceCriteriaJudgements) == 1


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
