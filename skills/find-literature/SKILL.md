---
name: Asta Literature Search
description: This skill should be used when the user asks to "find papers", "search for papers", "what does the literature say", "find research on", "academic papers about", "literature review", "cite papers", or needs to answer questions using academic literature.
allowed-tools:
  - Bash(asta literature find *)
  - Bash(asta papers *)
  - TaskOutput
  - Bash(jq *)
---

# Find Literature

Search academic literature for papers relevant to a query. The search will return a ranked list of papers with relevance scores, summaries, and supporting snippets. 

This is an advanced search, so the query can be long and complex. You may ask the user
questions to clarify the topic and refine the query before running the search.

## Installation

If `asta` command is not available install it using `uv tool install git+ssh://git@github.com/allenai/asta-plugins.git`

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/)

Verify installation with `asta literature --help`

## Tools Available

### Paper Finder

Run in background for comprehensive searches (30-60s):
```bash
# Saves to .asta/literature/find/YYYY-MM-DD-HH-MM-SS-{query-slug}.json by default
Bash(command="asta literature find 'query' --timeout 300", run_in_background=true)
```
The command saves results to `.asta/literature/find/` (in current working directory) by default with an auto-generated filename.
The filename is printed to the console when the search is finished. Use the TaskOutput tool to capture the filename for later processing

After the file has been created, index it using the [asta-documents](../asta-documents/SKILL.md) skill.

```bash
Bash(command="asta documents add file://<filename> --name=... --summary=...")
```

Browse results with jq:
```bash
jq '[.results | sort_by(-.relevanceScore) | .[0:10][] | {title, year, venue, corpusId, score: .relevanceScore, summary: .relevanceJudgement.relevanceSummary}]' <filename>
```

Go through all highly relevant papers, extracting relevance criteria, snippets, and citation contexts from each.

### Semantic Scholar CLI (fast targeted searches)

```bash
# Get paper details
asta papers get ARXIV:2005.14165

# Search papers
asta papers search "transformers" --year 2023- --limit 20

# Get citations
asta papers citations ARXIV:2005.14165

# Author search
asta papers author search "Geoffrey Hinton"
asta papers author papers <author_id>
```

Recommended fields: `--fields title,abstract,year,authors,venue,citationCount`

## JSON Structure

The output is a `LiteratureSearchResult` with the following structure:

**Top level:**
- `query`: string - the search query
- `results`: array of Paper objects

**Each paper in `results[]`:**
- `corpusId`: int - Semantic Scholar corpus ID
- `title`: string - paper title
- `abstract`: string | null - paper abstract
- `year`: int | null - publication year
- `authors`: array of {name: string, id: string}
- `venue`: string | null - publication venue
- `url`: string | null - Semantic Scholar URL
- `citationCount`: int | null - number of citations
- `relevanceScore`: float - 0-1 (higher = more relevant to query)
- `relevanceJudgement`: object with:
  - `relevance`: int - overall relevance score
  - `relevanceSummary`: string - AI explanation of relevance
  - `relevanceCriteriaJudgements`: array of per-concept judgements with:
    - `name`: string - concept name
    - `relevance`: int - relevance for this concept
    - `relevantSnippets`: array of supporting text excerpts
- `snippets`: array of text excerpts from paper body (if open access):
  - `text`: string - excerpt text
  - `sectionTitle`: string - section name
- `citationContexts`: array of citation contexts:
  - `text`: string - how other papers cite this work
  - `sourceCorpusId`: int - corpus ID of citing paper

Example access patterns:
```bash
# Top 10 papers by relevance
jq '[.results | sort_by(-.relevanceScore) | .[0:10][] | {title, year, score: .relevanceScore}]' <filename>

# Papers with relevance summary
jq '.results[] | {title, summary: .relevanceJudgement.relevanceSummary}' <filename>

# Extract snippets from a specific paper
jq '.results[] | select(.corpusId == 123456) | .snippets[].text' <filename>
```
