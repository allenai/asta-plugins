---
name: Literature Understanding
description: This skill should be used when the user asks to "find papers", "search for papers", "what does the literature say", "find research on", "academic papers about", "literature review", "cite papers", needs to answer questions using academic literature, wants to follow up on a previous search, continue a conversation about papers, narrow or broaden results, explore a new angle on an existing thread, generate a report, write a literature review, or synthesize findings. Use this for any interaction with the Paper Finder.
allowed-tools:
  - Bash(asta literature *)
  - Bash(asta papers *)
  - Write(.asta/literature/*)
  - Edit(.asta/literature/*)
  - Read(.asta/literature/*)
  - Read(*.json)
  - TaskOutput
  - Bash(jq *)
---

# Literature Understanding

Search, explore, and synthesize academic literature through conversations with the Paper Finder — an agentic backend that finds relevant papers, understands context across turns, and adapts its search strategy based on your follow-ups.

The query can be long and complex — natural language questions, keyword searches, author
lookups, or metadata queries with nested conditions (e.g. "papers by Hinton on dropout
published after 2020 in top-tier venues"). You may ask the user questions to clarify the
topic and refine the query before running the search.

All artifacts for a session are stored together in a human-readable folder:
```
~/.asta/literature/sessions/
    2026-03-09-143052-poetry-translation/
        thread.json                           # session state
        results-01-poetry-translation.json    # initial search results
        results-02-focus-on-llms.json         # follow-up results
        exports/
            results.bib
        report-poetry-translation.md          # synthesis report (when generated)
```

## Context Isolation Rules

- Work with **one thread at a time** — load state, interact, then move on
- Use **concise stdout** for decisions; full data lives in session files
- Reference threads by **thread ID** — never dump full results into context
- Read **summaries first** (`asta literature show`), drill into details only when needed
- **Each `asta literature find` creates a new session folder** — never overwrite or
  reuse an existing session's folder unless the user explicitly asks to

## Workflow

### 1. Start a Search (creates a session)

```bash
Bash(command="asta literature find 'protein folding benchmarks CASP15' --timeout 300", run_in_background=true)
```

Takes 30s–3min. When the `<task-notification>` arrives, use `TaskOutput` to read the result. Output:
```
Search completed successfully!
Thread: abc123
Papers found: 14
Session: ~/.asta/literature/sessions/2026-03-09-143052-protein-folding/
Results: ~/.asta/literature/sessions/.../results-01-protein-folding.json
Asta: REDACTED_ASTA_RC_URL/share/abc123
```

You can also write to a custom path (`-o results.json`) or stdout (`-o -`).

### 2. Follow Up

Send any follow-up message to the thread — the backend is agentic and understands
conversational context:

```bash
Bash(command="asta literature followup abc123 'focus on diffusion models'", run_in_background=true)
```

Each follow-up saves a new results file in the session:
```
Thread abc123 updated (turn 2)
Message: "focus on diffusion models"
Papers: 8 (was 14)
Top hits:
  1. "Diffusion-Based Protein Structure Generation" - Watson et al., 2024
  2. ...
Session: ~/.asta/literature/sessions/2026-03-09-143052-protein-folding/
Results: ~/.asta/literature/sessions/.../results-02-focus-on-diffusion-models.json
Asta: REDACTED_ASTA_RC_URL/share/abc123
```

### 3. Manage Sessions

```bash
# List all sessions
asta literature threads

# Summary view
asta literature show abc123

# Full JSON dump
asta literature show abc123 --full

# Export current results
asta literature export abc123 --format json
asta literature export abc123 --format bibtex
asta literature export abc123 --format csv
```

### 4. Semantic Scholar CLI (fast targeted lookups)

The Paper Finder also handles simple queries (keywords, author names, etc.) and will
return higher-quality results, but takes 30s–3min. Use the Semantic Scholar CLI when
you need fast, immediate lookups and don't need relevance ranking:

```bash
asta papers get ARXIV:2005.14165
asta papers search "transformers" --year 2023- --limit 20
asta papers citations ARXIV:2005.14165
asta papers author search "Geoffrey Hinton"
asta papers author papers <author_id>
```

Tips:
- Recommended fields: `--fields title,abstract,year,authors,venue,citationCount`
- Use smaller limits (10–20) for initial searches
- Use `--format json` for piping to jq, `--format text` for quick viewing

## Browse Results with jq

```bash
# Top 10 papers by relevance from a results file
jq '[.results | sort_by(-.relevanceScore) | .[0:10][] | {title, year, venue,
  corpusId, score: .relevanceScore,
  summary: .relevanceJudgement.relevanceSummary}]' RESULTS_FILE

# Top papers from thread state
jq '[.current_results[:5][] | {title, year,
  authors: [.authors[].name]}]' SESSION_DIR/thread.json

# All turn inputs
jq '[.turns[] | {turn: .turn_number, type, input,
  results: .result_count}]' SESSION_DIR/thread.json

# Relevance evidence for a specific paper
jq '.results[] | select(.corpusId == CORPUS_ID) | {title,
  criteria: [.relevanceJudgement.relevanceCriteriaJudgements[] |
  {concept: .name, relevance,
  evidence: [.relevantSnippets[].text]}]}' RESULTS_FILE

# Snippets from a specific paper
jq '.results[] | select(.corpusId == CORPUS_ID) | {title, abstract,
  snippets: [.snippets[]? | {section: .sectionTitle, text}]}' RESULTS_FILE

# Citation contexts
jq '[.results[] | select(.corpusId == CORPUS_ID) |
  .citationContexts[].text]' RESULTS_FILE
```

## Reports

When the user asks for a written deliverable (literature review, report, synthesis):

1. **Create the report file early** in the session folder — don't wait for all searches
   to complete. Use a descriptive filename like `report-<topic-slug>.md`
2. **Go through ALL highly relevant papers**, extracting relevance criteria, snippets,
   and citation contexts from each
3. **Update progressively** — add papers to References as you go, fill sections as
   themes emerge
4. **Synthesize** — connect ideas across papers, don't just list them
5. **Ensure completeness** — all background searches must finish before completing;
   all in-text citations must match references; executive summary reflects key findings

### Citation Format

Use citation keys with link definitions for clickable references:

```markdown
This was shown by [[Author2024]].

## References
- [[Author2024]] Author, A. (2024). Title. Venue.

[Author2024]: https://semanticscholar.org/p/CORPUS_ID
```

### Quality Standards

- **Comprehensive**: Cover all major themes and key papers
- **Evidence-based**: Support claims with paper evidence and citations
- **Synthesized**: Don't just list papers — connect ideas across papers
- **Well-structured**: Clear sections, logical flow
- **Properly cited**: All claims traced to sources

## Response Format (MANDATORY)

Every response MUST end with a links section containing the Asta URL and all local
file paths from the command's stderr output. Extract the paths from the `Session:`,
`Results:`, and `Asta:` lines.

IMPORTANT: Always expand `~` to the full absolute home directory path (e.g. `$HOME`)
and prepend `file://` so that paths are clickable in the terminal. For example,
`~/.asta/literature/...` becomes `file:///Users/markpolak/.asta/literature/...`.

Example:

```
**Links:**
- Asta: REDACTED_ASTA_RC_URL/share/abc123
- Session: file:///Users/markpolak/.asta/literature/sessions/2026-03-09-143052-protein-folding/
- Results: file:///Users/markpolak/.asta/literature/sessions/.../results-01-protein-folding.json
```

Do NOT omit this section.

## JSON Schema

The results JSON follows the `LiteratureSearchResult` schema (auto-generated from
`asta.literature.models`):

```json
{
  "query": "string — the search query",
  "response": "string — the Paper Finder agent's textual response",
  "results": [
    {
      "corpusId": 12345,
      "title": "string",
      "abstract": "string | null",
      "year": 2024,
      "authors": [{"name": "string", "authorId": "string"}],
      "venue": "string | null",
      "url": "string | null — Semantic Scholar URL",
      "publicationDate": "string | null — YYYY-MM-DD",
      "citationCount": 42,
      "categories": ["string"],
      "relevanceScore": 0.95,
      "relevanceJudgement": {
        "relevance": 5,
        "relevanceSummary": "string — AI explanation of why this paper is relevant",
        "relevanceCriteriaJudgements": [
          {
            "name": "string — concept name from the query",
            "relevance": 5,
            "relevantSnippets": [
              {"text": "string — excerpt supporting this judgement",
               "sectionTitle": "string | null"}
            ]
          }
        ]
      },
      "snippets": [
        {"text": "string — excerpt from paper body",
         "sectionTitle": "string | null"}
      ],
      "citationContexts": [
        {"text": "string — how another paper cites this work",
         "sourceCorpusId": 67890}
      ]
    }
  ]
}
```

Key fields for analysis:
- `relevanceScore` (float 0–1) — primary ranking signal
- `relevanceJudgement.relevanceSummary` — quick understanding of why a paper matters
- `relevanceJudgement.relevanceCriteriaJudgements` — per-concept evidence with snippets
- `snippets` — direct excerpts from the paper body (when open access)
- `citationContexts` — how other papers describe this work (useful for synthesis)

## Session Files

Each session folder at `~/.asta/literature/sessions/<slug>/` contains:
- `thread.json` — session state with thread_id, turns history, current results
- `results-NN-<slug>.json` — results for each turn (01 = initial search, 02+ = follow-ups)
- `exports/` — exported results (json, bibtex, csv)
- `report-<topic-slug>.md` — synthesis report (when generated)
