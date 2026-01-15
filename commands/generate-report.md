---
description: Generate a literature report using Asta's literature tools
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

# Generate Report

Generate a literature report by searching the academic literature and synthesizing findings.

## Using Paper Finder

Run in background (30-60s):
```
Bash(command="python3 ${CLAUDE_PLUGIN_ROOT}/servers/paper-finder/find_papers.py '$ARGUMENTS' --timeout 300", run_in_background=true)
```

When complete, a `<task-notification>` arrives with the task ID. Use TaskOutput to get the widget_id:
```
TaskOutput(task_id="<id>")  # Returns {widget_id, file_path, paper_count}
```

### Exploring Results with jq

**1. Browse papers** - page through sorted by relevance (adjust `[0:10]` for offset:limit):
```bash
jq '[.widget.results | sort_by(-.relevanceScore) | .[0:10][] | {title, year, venue, corpusId, citationCount, score: .relevanceScore, authors: (.authors | if length <= 4 then [.[].name] | join(", ") else ([.[0:3][].name] | join(", ")) + ", +" + (length - 4 | tostring) + ", " + .[-1].name end), summary: .relevanceJudgement.relevanceSummary}]' ~/.asta/widgets/'WIDGET_ID.json'
```

**2. Relevance evidence** - see how paper matches query-derived concepts:
```bash
jq '.widget.results[] | select(.corpusId == CORPUS_ID) | {title, criteria: [.relevanceJudgement.relevanceCriteriaJudgements[] | {concept: .name, relevance, evidence: [.relevantSnippets[].text]}]}' ~/.asta/widgets/'WIDGET_ID.json'
```

**3. Abstract & passages** - full content from the paper:
```bash
jq '.widget.results[] | select(.corpusId == CORPUS_ID) | {title, abstract, snippets: [.snippets[]? | {section: .sectionTitle, text}]}' ~/.asta/widgets/'WIDGET_ID.json'
```

**4. Citation contexts** - how other papers cite this work:
```bash
jq '[.widget.results[] | select(.corpusId == CORPUS_ID) | .citationContexts[].text]' ~/.asta/widgets/'WIDGET_ID.json'
```

### Widget Structure

Each paper in `.widget.results[]`:
- `title`, `year`, `venue`, `corpusId`, `abstract`, `authors[]`
- `relevanceScore`: 0-1 (higher = more relevant)
- `relevanceJudgement`:
  - `.relevanceSummary`: AI summary of relevance
  - `.relevanceCriteriaJudgements[]`: per-concept scores with `.name`, `.relevance` (1-3), `.relevantSnippets[]`
- `snippets[]`: excerpts from paper body (may be empty if not open access)
- `citationContexts[]`: how other papers describe/cite this work (useful for synthesis)

Launch a paper search in background at the start, then continue with Asta searches while it runs. Launch additional searches as needed after exploring initial results.

**Important**: Go through all highly relevant papers from the paper finder results, not just the top few. Extract relevance criteria, snippets, and citation contexts from each one.

## Using Asta Tools

Use `mcp__plugin_asta_asta__*` tools for fast, targeted searches:
- `search_papers_by_relevance` - keyword search
- `snippet_search` - find evidence and details inside papers
- `get_citations` - find follow-on work citing a paper
- `get_paper` / `get_paper_batch` - fetch paper metadata by ID

- When using `search_papers_by_relevance`, avoid `citations` or `references` fields - use `get_citations` separately
- Use smaller limits (10-15 papers) for initial searches
- Recommended fields: `title,abstract,year,authors,venue`

## Synthesis

**Create the report file immediately** after launching your initial searches. Add findings progressively as you discover them - don't wait until the end.

**Do not prematurely conclude you are done.** All background searches must complete before finishing. You must use the paper finder results, `snippet_search`, `get_citations`, etc. Once you receive the `<task-notification>` for each background search, use `TaskOutput` to get the widget_id, then use jq to read the widget JSON and update the report.

## Report References Format

Use citation keys with link definitions so citations are clickable and show brackets:
- Inline citations: `[[Yao2024]]` renders as `[Yao2024]` with brackets visible and clickable
- Add link definitions at the end of the file: `[Yao2024]: https://semanticscholar.org/p/CORPUS_ID`
- List references alphabetically by key in a References section

Example inline citation:
```
This approach was introduced by [[Yao2024]].
```

Example References section:
```
## References

- [[Yao2024]] Yao, S., et al. (2024). τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains. arXiv.
- [[Dou2025]] Dou, Z., et al. (2025). Another Paper Title. Venue.
```

Example link definitions (at end of file):
```
[Yao2024]: https://semanticscholar.org/p/270218537
[Dou2025]: https://semanticscholar.org/p/123456789
```

## Report File Workflow

Reports are saved to `~/.asta/reports/` as markdown files. The `~/.asta/reports/` and `~/.asta/widgets/` directories are pre-created by the session hook - do not run mkdir.

### 1. Create the report file early

At the start, create a report file with a slugified name based on $ARGUMENTS:
```
~/.asta/reports/YYYY-MM-DD-query-slug.md
```

Initialize it with a title and placeholder sections:
- Executive Summary (placeholder)
- Key themes/sections based on initial query understanding
- References (empty)

### 2. Edit progressively as you research

As you find relevant papers and insights:
- Add papers to the References section immediately
- Fill in section content as themes emerge
- Update the Executive Summary as the picture becomes clearer

This keeps the user informed of progress and avoids losing work.

### 3. Finalize before completing

Before finishing:
- Ensure all sections are complete
- Verify all in-text citations match references
- Add a generation date at the bottom
