---
description: Search for academic papers using Asta's paper finder agent
allowed-tools:
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/servers/paper-finder/find_papers.py *)
  - Read($HOME/.asta/widgets/*)
  - Bash(jq *)
---

# Find Papers

Search for academic papers using natural language queries.

## Instructions

1. Run the paper finder:
   ```bash
   Bash(command="python3 ${CLAUDE_PLUGIN_ROOT}/servers/paper-finder/find_papers.py '$ARGUMENTS' --timeout 300")
   ```
   This will block for 30-60 seconds while searching, then return `{widget_id, file_path, paper_count}`.

2. Use jq to browse the results (sorted by relevance):
   ```bash
   jq '[.widget.results | sort_by(-.relevanceScore) | .[0:10][] | {title, year, venue, corpusId, citationCount, score: .relevanceScore, authors: (.authors | if length <= 4 then [.[].name] | join(", ") else ([.[0:3][].name] | join(", ")) + ", +" + (length - 4 | tostring) + ", " + .[-1].name end), summary: .relevanceJudgement.relevanceSummary}]' ~/.asta/widgets/'WIDGET_ID.json'
   ```

3. Present results in a readable format that includes for each paper:
   - Title (bold)
   - Authors
   - Venue and year
   - Citation count
   - Relevance score and **relevance summary** (this explains why the paper matches the query)

4. After showing results, tell the user how they can explore further:
   - "To see more papers, ask me to show the next page" (adjust the `.[0:10]` slice in jq)
   - "To dive deeper into specific papers, ask me about them by name"

## Progressive Detail Levels

When the user asks for details on a specific paper, show information progressively:

### Level 1: Relevance Evidence (default when user asks about a paper)
Show why it matches the search (short snippets for each query concept):
```bash
jq '.widget.results[] | select(.corpusId == CORPUS_ID) | {title, criteria: [.relevanceJudgement.relevanceCriteriaJudgements[] | {concept: .name, relevance, evidence: [.relevantSnippets[].text]}]}' ~/.asta/widgets/'WIDGET_ID.json'
```

### Level 2: Abstract & Passages (if user wants more detail)
Show abstract and longer passages from the paper (passages may be empty if not open access):
```bash
jq '.widget.results[] | select(.corpusId == CORPUS_ID) | {title, abstract, snippets: [.snippets[]? | {section: .sectionTitle, text}]}' ~/.asta/widgets/'WIDGET_ID.json'
```

### Level 3: Citation Contexts (if user wants to see how others cite this paper)
Show how other papers describe/cite this work:
```bash
jq '[.widget.results[] | select(.corpusId == CORPUS_ID) | .citationContexts[].text]' ~/.asta/widgets/'WIDGET_ID.json'
```

## Data Structure Reference

| Field | Source | Purpose |
|-------|--------|---------|
| `relevanceJudgement.relevanceCriteriaJudgements[].relevantSnippets` | From paper | Short excerpts proving relevance to search concepts |
| `snippets` | From paper | Longer passages for reading (requires full-text access) |
| `citationContexts` | From citing papers | How other papers describe/cite this work |
