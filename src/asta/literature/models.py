"""Pydantic models for literature search results"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Author(BaseModel):
    """Author information"""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    id: str = Field(alias="authorId", default="")


class Snippet(BaseModel):
    """Text snippet from paper body"""

    text: str
    sectionTitle: str | None = None
    sentenceIds: list[str] = Field(default_factory=list)


class RelevantSnippet(BaseModel):
    """Snippet supporting relevance judgement"""

    text: str
    sectionTitle: str | None = None
    sentenceIds: list[str] = Field(default_factory=list)


class RelevanceCriteriaJudgement(BaseModel):
    """Per-concept relevance judgement"""

    name: str
    relevance: int
    relevantSnippets: list[RelevantSnippet] = Field(default_factory=list)
    numOfOmittedRelevanceSnippetsDueLegal: int = 0


class RelevanceJudgement(BaseModel):
    """Overall relevance judgement for a paper"""

    relevance: int
    relevanceSummary: str
    relevanceCriteriaJudgements: list[RelevanceCriteriaJudgement] = Field(
        default_factory=list
    )


class CitationContext(BaseModel):
    """Context where this paper is cited by another paper"""

    text: str
    sourceCorpusId: int
    withinSnippetOffsetStart: int | None = None
    withinSnippetOffsetEnd: int | None = None
    sourceSentenceIds: list[str] = Field(default_factory=list)


class Paper(BaseModel):
    """Paper search result with relevance judgements"""

    model_config = ConfigDict(populate_by_name=True)

    # Use validation_alias to accept snake_case from API
    corpusId: int = Field(validation_alias="corpus_id")
    title: str
    abstract: str | None = None
    year: int | None = None
    authors: list[Author] = Field(default_factory=list)
    venue: str | None = None
    journal: dict[str, Any] | None = None
    url: str | None = None
    publicationDate: str | None = Field(
        default=None, validation_alias="publication_date"
    )
    citationCount: int | None = Field(default=None, validation_alias="citation_count")
    categories: list[str] = Field(default_factory=list)

    # Asta Paper Finder specific fields
    relevanceScore: float = Field(validation_alias="relevance_score")
    relevanceJudgement: RelevanceJudgement | None = Field(
        default=None, validation_alias="relevance_judgement"
    )
    snippets: list[Snippet] = Field(default_factory=list)
    citationContexts: list[CitationContext] = Field(
        default_factory=list, validation_alias="citation_contexts"
    )

    # Legal/filtering fields
    legalToShow: bool = Field(default=True, validation_alias="legal_to_show")
    numOfOmittedCitationContextsDueLegal: int = Field(
        default=0, validation_alias="num_of_omitted_citation_contexts_due_legal"
    )

    @field_validator("authors", mode="before")
    @classmethod
    def convert_author_strings(cls, v):
        """Convert author strings to Author objects if needed."""
        if not isinstance(v, list):
            return v
        result = []
        for author in v:
            if isinstance(author, str):
                # Convert string to Author dict
                result.append({"name": author, "id": ""})
            else:
                result.append(author)
        return result


class LiteratureSearchResult(BaseModel):
    """Complete literature search result"""

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Results from Asta Paper Finder with relevance-ranked papers"
        }
    )

    query: str
    results: list[Paper]
