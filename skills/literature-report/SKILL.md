---
name: Literature Report Generation
description: This skill should be used when the user asks to "generate a report", "write a literature review", "create a comprehensive summary", "synthesize the literature", or needs a detailed written report on an academic topic. Use this for thorough, multi-paper synthesis tasks that produce written deliverables. Can work with existing paper-finder results or launch new searches.
allowed-tools:
  - Bash(asta literature find *)
  - Bash(asta papers *)
  - Write(.asta/literature/report/*)
  - Edit(.asta/literature/report/*)
  - Read(.asta/literature/*)
  - Read(*.json)
  - TaskOutput
  - Bash(jq *)
---

# Literature Report Generation

Generate comprehensive literature reports by searching academic literature, analyzing papers, and synthesizing findings into a well-structured markdown document.

## When to Use This Skill

- User asks for a literature review or comprehensive report
- Task requires synthesizing multiple papers into a coherent narrative
- User wants a written deliverable (not just a list of papers)
- Topic requires deep exploration with citations and evidence
- User has existing paper-finder results and wants a comprehensive report from them

## Workflow

### 1. Check for Existing Results

**If the user provides an existing paper-finder results file:**
- Ask them to confirm the file path
- Use Read tool to verify the file exists and is valid JSON
- Skip to step 3 to process those results directly

**If no existing results file:**
- Proceed to launch a new search below

### 2. Launch Background Searches (if needed)

Start with the paper finder in background (30-60s):
```bash
# Uses default location .asta/literature/find/YYYY-MM-DD-HH-MM-SS-{query-slug}.json
Bash(command="asta literature find 'query' --timeout 300", run_in_background=true)

# Or specify a custom output location
Bash(command="asta literature find 'query' --timeout 300 -o custom-results.json", run_in_background=true)
```

Launch additional targeted CLI searches as needed while paper finder runs.

### 3. Create Report File Immediately

Don't wait for searches to complete. Create the report file early with:
- Default file path: `.asta/literature/report/YYYY-MM-DD-topic-slug.md` (in current working directory)
- Custom path: User can specify a different location if desired
- Initial structure: Title, Executive Summary (placeholder), section headings, References

This keeps the user informed and avoids losing work.

### 4. Process Paper Finder Results

**If using existing results file:**
- Use the file path provided by the user
- Read it with the Read tool to understand the query and papers

**If launched a new search:**
- When `<task-notification>` arrives, use TaskOutput to get the results:
```bash
TaskOutput(task_id="<id>")
```
- The results file will be at `.asta/literature/find/` (check TaskOutput for the exact filename), or at the path you specified with `-o`

Browse results with jq (sorted by relevance):
```bash
# Replace RESULTS_FILE with the actual path from TaskOutput or your custom path
jq '[.results | sort_by(-.relevanceScore) | .[0:10][] | {title, year, venue, corpusId, citationCount, score: .relevanceScore, authors: (.authors | if length <= 4 then [.[].name] | join(", ") else ([.[0:3][].name] | join(", ")) + ", +" + (length - 4 | tostring) + ", " + .[-1].name end), summary: .relevanceJudgement.relevanceSummary}]' RESULTS_FILE
```

**Important**: Go through ALL highly relevant papers (not just top few). Extract:
- Relevance criteria and evidence
- Snippets from paper body
- Citation contexts (how others cite this work)

### 5. Deep Dive on Key Papers

For each important paper, extract detailed evidence:

**Relevance evidence**:
```bash
jq '.results[] | select(.corpusId == CORPUS_ID) | {title, criteria: [.relevanceJudgement.relevanceCriteriaJudgements[] | {concept: .name, relevance, evidence: [.relevantSnippets[].text]}]}' RESULTS_FILE
```

**Abstract and passages**:
```bash
jq '.results[] | select(.corpusId == CORPUS_ID) | {title, abstract, snippets: [.snippets[]? | {section: .sectionTitle, text}]}' RESULTS_FILE
```

**Citation contexts** (how others describe this work):
```bash
jq '[.results[] | select(.corpusId == CORPUS_ID) | .citationContexts[].text]' RESULTS_FILE
```

Replace `RESULTS_FILE` with the actual results file path (found in `.asta/literature/find/`, user-provided, or from TaskOutput).

### 6. Use CLI Tools for Targeted Research

Supplement paper finder with fast, targeted searches using `asta papers`:

```bash
# Search for papers
asta papers search "keyword" --year 2023- --limit 20 --fields title,abstract,year,authors

# Get paper details
asta papers get ARXIV:2005.14165 --fields title,abstract,authors,year

# Get citations
asta papers citations CorpusId:12345 --limit 50

# Author papers
asta papers author search "Author Name"
asta papers author papers <author_id> --limit 50
```

Tips:
- Use smaller limits (10-20) for initial searches
- Recommended fields: `title,abstract,year,authors,venue,citationCount`
- Use `--format json` for piping to jq, `--format text` for quick viewing

### 7. Update Report Progressively

As you gather information:
- Add papers to References section immediately
- Fill in section content as themes emerge
- Update Executive Summary as understanding develops
- Use proper citation format (see below)

**Do not wait until the end to write everything.** Edit progressively.

### 8. Ensure Completeness Before Finishing

Before completing:
- If launched background searches: All searches must finish (check for pending `<task-notification>`)
- All sections must be filled in
- All in-text citations must match references
- Executive summary reflects key findings
- Add generation date at bottom

## JSON Structure

Paper finder results use the `LiteratureSearchResult` format (see **Find Literature** skill for complete structure documentation).

Key fields for report generation:
- `.query` - the search query
- `.results[]` - array of papers sorted by relevance
- `.results[].relevanceScore` - 0-1 relevance score
- `.results[].relevanceJudgement.relevanceSummary` - AI explanation
- `.results[].relevanceJudgement.relevanceCriteriaJudgements[]` - per-concept evidence
- `.results[].snippets[]` - text excerpts from paper body
- `.results[].citationContexts[]` - citation contexts from other papers

## Citation Format

Use citation keys with link definitions for clickable citations:

**Inline citations**:
```markdown
This was demonstrated by [[Yao2024]].
```

**References section**:
```markdown
## References

- [[Yao2024]] Yao, S., et al. (2024). τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains. arXiv.
- [[Dou2025]] Dou, Z., et al. (2025). Another Paper Title. Venue Name.
```

**Link definitions** (at end of file):
```markdown
[Yao2024]: https://semanticscholar.org/p/270218537
[Dou2025]: https://semanticscholar.org/p/123456789
```

This makes `[[Yao2024]]` render as `[Yao2024]` with visible brackets and clickable links to Semantic Scholar.

## Quality Standards

- **Comprehensive**: Cover all major themes and key papers
- **Evidence-based**: Support claims with paper evidence and citations
- **Synthesized**: Don't just list papers - connect ideas across papers
- **Well-structured**: Clear sections, logical flow
- **Properly cited**: All claims traced to sources
- **Up-to-date**: Focus on recent work when relevant
