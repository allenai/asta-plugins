---
name: semantic-scholar
description: Look up or search papers, authors, citations, and full-text snippets on Semantic Scholar. Use for fast, targeted queries about a paper, author, or specific named research artifact (benchmark, dataset, model, method, etc.) — not comprehensive reports.
allowed-tools: Bash(asta papers *)
---

# Semantic Scholar Lookup

    Fast, targeted lookups of paper metadata, citations, and authors using the Semantic Scholar API via `asta papers` commands.

## When to Use This Skill

- User asks for details about a specific paper (by title, DOI, arXiv ID, etc.)
- User wants to see papers citing a given work
- User asks about an author's papers
- User wants a quick keyword search (not a comprehensive report)
- User wants to find specific claims, methods, or evidence within paper full text (use `snippet-search`)
- Task requires targeted paper metadata or citation graphs

**Not for comprehensive reports** - use the Literature Report Generation skill for that.

## Related: Find Literature skill

`asta papers ...` (this skill) is for **mechanical, targeted lookups** against the Semantic
Scholar API: fetch a known paper, list citations, search by keyword across titles / abstracts /
bodies, look up an author. There is no agent-mediated reasoning beyond S2's own keyword ranking.

The **Find Literature skill** (`asta literature find` / `asta literature interactive`) is for
**topic-driven, criterion-based search**, where the system extracts relevance criteria from the
query, retrieves candidates, and ranks them against those criteria with per-paper relevance
summaries — closer to "literature search as a graded judgement" than to a keyword match.

Use **this** skill (`asta papers`) when:

- The user names a specific paper, author, ID, or exact phrase to look up
- You need raw metadata (citations, venue, fields of study, openAccessInfo)
- You're navigating a citation graph (who cites what, who an author has cited)
- You want to grep for a specific string in paper bodies (`snippet-search`)
- You need a fast result and exhaustive coverage isn't required

Use the **Find Literature** skill instead when:

- The user asks "find papers on X", "what does the literature say about Y", "papers that argue Z"
- The query is a research topic, not a string match — and ranked relevance with explanations matters
- The work session is exploratory: filtering prior results, aggregating, following relations across
  multiple turns (use `asta literature interactive --thread-dir <dir>`)
- A `find`-style one-shot or `interactive`-style multi-turn agent loop with verification will
  produce a better-ranked result than raw keyword search

The two are complementary. A common flow: use Find Literature to discover relevant papers on a
topic, then `asta papers get` / `asta papers citations` to drill into specific ones.

**Session-level rule of thumb:** if the session as a whole is about literature
search/exploration (e.g. the first user turn is "find papers on X"), default to
`asta literature interactive` for the discovery work, even when individual queries look simple.
Reach for `asta papers` when the session is about something else and a quick metadata or
citation lookup is just one step inside it.

## Installation

This skill requires the `asta` CLI:

```bash
# Install/reinstall at the correct version
PLUGIN_VERSION=0.18.0
if [ "$(asta --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" != "$PLUGIN_VERSION" ]; then
  uv tool install --force git+https://github.com/allenai/asta-plugins.git@v$PLUGIN_VERSION
fi
```

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/)

## Available Commands

### Get Paper Details

**asta papers get** - Get metadata for a single paper by ID

```bash
asta papers get ARXIV:2005.14165

asta papers get "DOI:10.18653/v1/N18-3011" --fields title,year,authors,abstract

asta papers get CorpusId:215416146 --format text
```

Supported ID formats:
- `ARXIV:2106.15928`
- `DOI:10.18653/v1/N18-3011`
- `CorpusId:215416146`
- `PMID:19872477`
- `URL:https://arxiv.org/abs/2106.15928`

Common fields: `title,abstract,authors,year,venue,citationCount,publicationDate,url,isOpenAccess,fieldsOfStudy`

### Search Papers

**asta papers search** - Keyword-based paper search

```bash
asta papers search "transformers attention mechanism"

asta papers search "RLHF" --date 2023- --limit 10

asta papers search "neural networks" --fields title,year,abstract,authors

asta papers search "LLM safety" --date 2024-01-01:2024-12-31
```

Options:
- `--fields`: Comma-separated fields to return
- `--limit`: Number of results (default 20, max 100)
- `--date`: Publication date or year filter. Accepts years (`2020`, `2020-2024`, `2020-`) or date ranges (`2024-01-01:2024-12-31`). Maps to the S2 `publicationDateOrYear` parameter.
- `--format`: Output as `json` or `text`

### Snippet Search

**asta papers snippet-search** - Search over paper full text (title, abstract, and body) via the S2 snippet/search API. Returns matching text excerpts alongside paper metadata.

```bash
asta papers snippet-search "in-context learning emerges at scale"

asta papers snippet-search "RLHF reward hacking" --date 2023- --limit 10

asta papers snippet-search "sparse mixture of experts" --fields snippet.text,snippet.snippetKind,snippet.section

# Pin results to papers indexed before a date (useful for reproducible benchmarks)
asta papers snippet-search "chain-of-thought" --inserted-before 2024-01-01
```

The `--fields` option accepts **snippet fields**:

- `snippet.text` - The matched text excerpt (~500 words)
- `snippet.snippetKind` - Source type (e.g., title, abstract, body)
- `snippet.section` - Paper section the snippet came from
- `snippet.snippetOffset` - Character position data (`start`, `end`)
- `snippet.annotations` - Markup including reference mentions and sentence boundaries

If `--fields` is omitted, the default is `snippet.text,snippet.snippetKind`. Paper metadata (corpusId, title, authors, openAccessInfo) and relevance score are always returned regardless of `--fields`.

Options:
- `--fields`: Comma-separated snippet fields to return
- `--date`: Date/year filter, same as standard search
- `--limit`: Max results (default 20, max 1000 — higher ceiling than standard search)
- `--inserted-before`: Only include papers indexed before this date (`YYYY-MM-DD`, `YYYY-MM`, or `YYYY`). Typically used for consistency in benchmarking — pinning a cutoff date ensures the same set of papers is returned across repeated runs, even as new papers are continuously indexed.
- `--format`: Output as `json` or `text`

### Get Citations

**asta papers citations** - Papers that cite a given work

```bash
asta papers citations ARXIV:2005.14165

asta papers citations CorpusId:218487638 --limit 20 --format text
```

Options:
- `--fields`: Fields for citing papers
- `--limit`: Max results (default 50, max 1000)
- `--format`: Output as `json` or `text`

### Author Search and Papers

**asta papers author search** - Find authors by name

```bash
asta papers author search "Yoav Goldberg"

asta papers author search "Hinton" --limit 5 --format text
```

**asta papers author papers** - Get papers by an author

```bash
# First, get author ID from search
asta papers author search "Yoav Goldberg"

# Then get their papers using the author ID
asta papers author papers 1741101 --limit 50

asta papers author papers 1741101 --fields title,year,venue,citationCount
```

Options:
- `--fields`: Fields to return for papers
- `--limit`: Max results (default 50, max 1000)
- `--format`: Output as `json` or `text`

## Output Formats

All commands support two output formats:

**JSON format** (default):
- Machine-readable
- Complete data structure
- Pipe to `jq` for filtering
- Best for programmatic use

**Text format** (`--format text`):
- Human-readable
- Formatted output
- Best for quick browsing
- Use when showing results to user

## Usage Tips

### Efficient Field Selection

Only request fields you need for faster responses:

```bash
# Good - minimal fields for quick browse
asta papers search "deep learning" --fields title,year,authors,citationCount

# Less efficient - many fields slow down response
asta papers search "deep learning" --fields title,abstract,authors,year,venue,citations,references
```

### Date Filtering

Restrict to recent papers when appropriate:

```bash
asta papers search "RLHF" --date 2023-2024  # 2023-2024
asta papers search "RLHF" --date 2023-      # 2023 onwards
asta papers search "RLHF" --date -2020      # Before 2020
asta papers search "RLHF" --date 2024-06-01:2024-12-31  # Specific date range
```

### Piping to jq

For complex JSON processing:

```bash
# Extract just titles
asta papers search "transformers" | jq '.data[].title'

# Filter by citation count
asta papers search "neural networks" | jq '.data[] | select(.citationCount > 100)'

# Get author names
asta papers get ARXIV:2005.14165 | jq '.authors[].name'
```

### Multi-Step Workflows

Chain commands for complex queries:

**Example 1: Find highly-cited recent papers by an author**
```bash
# 1. Find author
asta papers author search "Geoffrey Hinton" --format text

# 2. Get their recent papers
asta papers author papers 1751273 --fields title,year,citationCount --limit 50 | \
  jq '.data[].paper | select(.year >= 2020) | select(.citationCount > 100)'
```

**Example 2: Explore citation network**
```bash
# 1. Get paper details
asta papers get ARXIV:2005.14165

# 2. Get who cited it
asta papers citations ARXIV:2005.14165 --limit 20 --format text

# 3. Get details on specific citing papers
asta papers get CorpusId:123456789
```

## Example Workflows

### "Get details for arXiv:2005.14165"

```bash
asta papers get ARXIV:2005.14165 --format text
```

Present the output to user in a readable format.

### "What papers cite the GPT-3 paper?"

```bash
# GPT-3 paper
asta papers citations ARXIV:2005.14165 --limit 50 --format text
```

Show recent/highly-cited papers from the results.

### "Recent papers on RLHF"

```bash
asta papers search "RLHF reinforcement learning from human feedback" \
  --date 2023- \
  --limit 20 \
  --fields title,abstract,year,authors,venue,citationCount \
  --format text
```

### "Papers by Yoav Goldberg"

```bash
# Step 1: Find author
asta papers author search "Yoav Goldberg" --format text

# Step 2: Get their papers (using author ID from step 1)
asta papers author papers 1741101 \
  --fields title,year,venue,citationCount \
  --limit 50 \
  --format text
```

### "Find evidence of 'chain-of-thought' reasoning"

```bash
# Snippet search finds mentions in paper bodies, not just titles/abstracts
asta papers snippet-search "chain-of-thought reasoning improves performance" \
  --limit 15

# Or use standard search for paper-level results
asta papers search "chain-of-thought reasoning" \
  --fields title,abstract,year,authors \
  --limit 15

# Then examine specific papers with 'asta papers get'
```

## Response Presentation

When showing results to users:

**For single paper**:
```
**Title** (Year)
Authors: [author list]
Venue: [venue name]
Citations: [count]

[Abstract]

URL: [Semantic Scholar link]
```

**For paper lists**:
```
Found [N] papers:

1. **Paper Title** - Author et al. (Year) - [Venue] - [X citations]
2. **Another Paper** - ...
...
```

**For snippet results** (`snippet-search`):
```
Found [N] snippet results:

1. **Paper Title** - Author et al.
   Score: 0.95
   Snippet (abstract): "...matching text excerpt..."
2. **Another Paper** - ...
...
```

**For citations**:
```
Found [N] papers citing this work:

Recent citations:
1. [Paper 1] (2024) - [citations]
2. [Paper 2] (2023) - [citations]
...
```

## Best Practices

- Use `--format text` when showing results directly to user
- Use JSON output when you need to process or filter results
- Start with small limits, increase if needed
- Only fetch fields you'll actually use
- Use `snippet-search` when searching for specific claims, methods, or evidence within paper bodies
- Use `search` for topic-level paper discovery
- For comprehensive research, suggest Literature Report Generation skill instead
- Provide Semantic Scholar URLs when helpful (`https://semanticscholar.org/paper/{paperId}`)

## API Key

The commands use the `ASTA_TOOL_KEY` environment variable if available. Most queries work without a key, but a key provides higher rate limits.
