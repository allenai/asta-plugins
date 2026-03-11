"""Pydantic models for literature search results"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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

    corpusId: int
    title: str
    abstract: str | None = None
    year: int | None = None
    authors: list[Author] = Field(default_factory=list)
    venue: str | None = None
    journal: dict[str, Any] | None = None
    url: str | None = None
    publicationDate: str | None = None
    citationCount: int | None = None
    categories: list[str] = Field(default_factory=list)

    # Asta Paper Finder specific fields
    relevanceScore: float
    relevanceJudgement: RelevanceJudgement | None = None
    snippets: list[Snippet] = Field(default_factory=list)
    citationContexts: list[CitationContext] = Field(default_factory=list)

    # Legal/filtering fields
    legalToShow: bool = True
    numOfOmittedCitationContextsDueLegal: int = 0


class LiteratureSearchResult(BaseModel):
    """Complete literature search result"""

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Results from Asta Paper Finder with relevance-ranked papers"
        }
    )

    query: str
    results: list[Paper]


class Turn(BaseModel):
    """A single turn in a multi-turn literature search thread."""

    turn_number: int
    type: Literal["search", "followup"]
    input: str
    timestamp: str
    result_count: int


class ThreadState(BaseModel):
    """Persisted state for a multi-turn literature search thread."""

    thread_id: str
    widget_id: str
    session_slug: str = ""
    user_id: str = ""
    created_at: str
    updated_at: str
    turns: list[Turn] = Field(default_factory=list)
    current_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
