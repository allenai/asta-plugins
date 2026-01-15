---
name: Literature Research
description: This skill should be used when the user asks to "find papers", "search for papers", "what does the literature say", "find research on", "academic papers about", "literature review", "cite papers", or needs to answer questions using academic literature.
allowed-tools:
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/servers/paper-finder/find_papers.py *)
  - mcp__plugin_asta_asta__get_paper
  - mcp__plugin_asta_asta__get_paper_batch
  - mcp__plugin_asta_asta__get_citations
  - mcp__plugin_asta_asta__search_authors_by_name
  - mcp__plugin_asta_asta__get_author_papers
  - mcp__plugin_asta_asta__search_papers_by_relevance
  - mcp__plugin_asta_asta__search_paper_by_title
  - mcp__plugin_asta_asta__snippet_search
  - Write($HOME/.asta/reports/*)
  - Edit($HOME/.asta/reports/*)
  - Read($HOME/.asta/reports/*)
  - Read($HOME/.asta/widgets/*)
  - TaskOutput
  - Bash(jq *)
---

# Literature Research

Search academic literature, answer questions with citations, and create literature reports.

## Tools Available

### Paper Finder

Run in background for comprehensive searches (30-60s):
```bash
Bash(command="python3 ${CLAUDE_PLUGIN_ROOT}/servers/paper-finder/find_papers.py 'query' --timeout 300", run_in_background=true)
```

Returns `{widget_id, file_path, paper_count}`. Results are in `~/.asta/widgets/WIDGET_ID.json`.

Browse results with jq:
```bash
jq '[.widget.results | sort_by(-.relevanceScore) | .[0:10][] | {title, year, venue, corpusId, score: .relevanceScore, summary: .relevanceJudgement.relevanceSummary}]' ~/.asta/widgets/'WIDGET_ID.json'
```

Go through all highly relevant papers, extracting relevance criteria, snippets, and citation contexts from each.

### Asta MCP Tools (fast targeted searches)

- `mcp__plugin_asta_asta__search_papers_by_relevance` - keyword search
- `mcp__plugin_asta_asta__snippet_search` - find evidence inside papers
- `mcp__plugin_asta_asta__get_citations` - papers citing a work
- `mcp__plugin_asta_asta__get_paper` / `get_paper_batch` - fetch by ID

Recommended fields: `title,abstract,year,authors,venue`

## Widget JSON Structure

Each paper in `.widget.results[]`:
- `title`, `year`, `venue`, `corpusId`, `abstract`, `authors[]`
- `relevanceScore`: 0-1 (higher = more relevant)
- `relevanceJudgement.relevanceSummary`: AI summary of relevance
- `relevanceJudgement.relevanceCriteriaJudgements[]`: per-concept scores with evidence
- `snippets[]`: excerpts from paper body
- `citationContexts[]`: how other papers cite this work

## Reports

Save to `~/.asta/reports/YYYY-MM-DD-slug.md`. Create early, update progressively.

Citation format - use bracketed links:
```markdown
This was shown by [[Author2024]].

## References
- [[Author2024]] Author, A. (2024). Title. Venue.

[Author2024]: https://semanticscholar.org/p/CORPUS_ID
```
