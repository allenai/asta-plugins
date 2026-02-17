---
name: Semantic Scholar Lookup
description: This skill should be used when the user asks to "get paper details", "look up a paper", "find citations", "who cited this paper", "papers by [author]", "search for papers on [topic]", or needs quick lookups of paper metadata, citations, or author information from Semantic Scholar. Use this for fast, targeted queries (not comprehensive reports).
allowed-tools:
  - Bash(asta papers *)
---

# Semantic Scholar Lookup

Fast, targeted lookups of paper metadata, citations, and authors using the Semantic Scholar API via `asta papers` commands.

## When to Use This Skill

- User asks for details about a specific paper (by title, DOI, arXiv ID, etc.)
- User wants to see papers citing a given work
- User asks about an author's papers
- User wants a quick keyword search (not a comprehensive report)
- Task requires targeted paper metadata or citation graphs

**Not for comprehensive reports** - use the Literature Report Generation skill for that.

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

asta papers search "RLHF" --year 2023- --limit 10

asta papers search "neural networks" --fields title,year,abstract,authors
```

Options:
- `--fields`: Comma-separated fields to return
- `--limit`: Number of results (default 20, max 100)
- `--year`: Year filter (e.g., `2020`, `2020-2024`, `2020-`)
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

### Year Filtering

Restrict to recent papers when appropriate:

```bash
asta papers search "RLHF" --year 2023:2024  # 2023-2024
asta papers search "RLHF" --year 2023-      # 2023 onwards
asta papers search "RLHF" --year :2020      # Before 2020
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
  --year 2023- \
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
# Search for papers discussing this
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
- For comprehensive research, suggest Literature Report Generation skill instead
- Provide Semantic Scholar URLs when helpful (`https://semanticscholar.org/paper/{paperId}`)

## API Key

The commands use the `ASTA_TOOL_KEY` environment variable if available. Most queries work without a key, but a key provides higher rate limits.
