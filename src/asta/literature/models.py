"""Pydantic models for literature search results"""

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


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

    model_config = ConfigDict(populate_by_name=True)

    text: str
    sectionTitle: str | None = Field(
        default=None, validation_alias=AliasChoices("sectionTitle", "section_title")
    )
    sentenceIds: list[str] = Field(default_factory=list)


class RelevanceCriteriaJudgement(BaseModel):
    """Per-concept relevance judgement.

    Tolerant of both wire shapes: the a2a artifact ({name, relevance, relevantSnippets}) and the
    enriched headless endpoints ({name, relevance, evidence})."""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    relevance: int | None = None
    relevantSnippets: list[RelevantSnippet] = Field(
        default_factory=list,
        validation_alias=AliasChoices("relevantSnippets", "relevant_snippets", "evidence"),
    )
    numOfOmittedRelevanceSnippetsDueLegal: int = 0


class RelevanceJudgement(BaseModel):
    """Overall relevance judgement for a paper.

    Tolerant of both wire shapes: the a2a artifact ({relevance, relevanceSummary,
    relevanceCriteriaJudgements}) and the enriched headless endpoints ({relevance, summary,
    criteria}) — previously relevanceSummary was REQUIRED, which would crash parsing the
    headless shape."""

    model_config = ConfigDict(populate_by_name=True)

    relevance: int
    relevanceSummary: str | None = Field(
        default=None,
        validation_alias=AliasChoices("relevanceSummary", "relevance_summary", "summary"),
    )
    relevanceCriteriaJudgements: list[RelevanceCriteriaJudgement] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "relevanceCriteriaJudgements", "relevance_criteria_judgements", "criteria"
        ),
    )


class Origin(BaseModel):
    """Which retrieval operation surfaced a paper (per-result provenance from paper-finder).
    Each operation = its own capture occasion for coverage estimation; total_hits = backend's
    total matches BEFORE top-k truncation (S2 search + snowball; dense has none)."""

    model_config = ConfigDict(populate_by_name=True)

    query_type: str
    provider: str | None = None
    dataset: str | None = None
    variant: str | None = None
    query: str | None = None
    iteration: int | None = None
    ranks: list[int] | None = None
    total_hits: int | None = None


class RejectedItem(BaseModel):
    """Slim row from the pipeline's rejected-sample (id/title/scores/origins only)."""

    model_config = ConfigDict(populate_by_name=True)

    corpus_id: str
    title: str | None = None
    relevance: int | None = None
    score: float | None = None
    drop_stage: str
    origins: list[str] | None = None
    best_rank: int | None = None


class RejectedSummary(BaseModel):
    """Statistics about docs paper-finder dropped (opt-in via include_rejected). Written to a
    SIDECAR file by the CLI — coverage scripts read it programmatically; it never lands in the
    main results file or the session's context."""

    model_config = ConfigDict(populate_by_name=True)

    counts_by_stage: dict[str, int] = Field(default_factory=dict)
    judged_grade_counts: dict[str, int] = Field(default_factory=dict)
    counts_by_origin: dict[str, int] = Field(default_factory=dict)
    sample: list[RejectedItem] | None = None


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

    # Use validation_alias to accept snake_case from API. The A2A artifact path
    # delivers corpusId as a string under s2Metadata; coerce digit-strings to int.
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
    origins: list[Origin] | None = None

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

    @field_validator("corpusId", mode="before")
    @classmethod
    def coerce_corpus_id(cls, v):
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return v


class LiteratureSearchResult(BaseModel):
    """Complete literature search result"""

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Results from Asta Paper Finder with relevance-ranked papers"
        }
    )

    query: str
    results: list[Paper]
    # Populated by `asta literature interactive` to identify the conversation
    # so a follow-up call can resume it. None for one-shot `asta literature find`.
    thread_id: str | None = None
    # Opt-in drop statistics (include_rejected != "none") — the CLI moves this to a sidecar
    # file before writing the main results.
    rejected: RejectedSummary | None = None
    narrative: str | None = None
