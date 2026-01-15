# Asta Plugins

Plugins by the [Asta](REDACTED_ASTA_PROD_URL) team for Claude Code.

## What's Included

### MCP Servers

| Server | Description |
|--------|-------------|
| **asta** | Semantic Scholar API tools (get_paper, search_papers, citations, etc.) |

### Commands

| Command | Description |
|---------|-------------|
| `/generate-report` | Generate literature reports from academic search |
| `/find-papers` | AI-powered natural language paper search |

## Installation

In Claude Code, run:

```
/plugin marketplace add allenai/asta-plugins
/plugin install asta@asta-plugins
```

Or load from a local directory for development:

```bash
claude --plugin-dir /path/to/asta-plugins
```

## Requirements

- Claude Code
- Python 3.10+

## Setup

### API Key

The `asta` MCP server may require an API key:

1. Request a key at [allenai.org/asta/resources/mcp](https://allenai.org/asta/resources/mcp)
2. Set the environment variable:
   ```bash
   export ASTA_TOOL_KEY="your-api-key"
   ```

## Usage

### Generate Literature Report

```
/asta:generate-report recent advances in RLHF for language models
```

Creates a comprehensive literature report saved to `~/.asta/reports/`.

### Find Papers (AI-powered)

```
/asta:find-papers recent papers on RLHF and language models
```

Results are saved to `~/.asta/widgets/` for later reference.

### Semantic Scholar API

```
Get details for arXiv:2005.14165
```

```
What papers cite the GPT-3 paper?
```

## Available Tools

### From `asta` server (Semantic Scholar)

- `get_paper` - Get paper details by ID (DOI, arXiv, CorpusId, etc.)
- `get_paper_batch` - Get multiple papers at once
- `get_citations` - Get papers citing a given paper
- `search_papers_by_relevance` - Keyword search for papers
- `search_paper_by_title` - Search by title
- `snippet_search` - Find text snippets inside papers
- `search_authors_by_name` - Search for authors
- `get_author_papers` - Get papers by an author

### Paper Finder CLI

The `/find-papers` and `/generate-report` commands use a CLI script for AI-powered paper search. Results are saved to `~/.asta/widgets/` as JSON for exploration with `jq`.

## Development

### Running Tests

```bash
uv run --extra test pytest -v
```

### Linting and Formatting

```bash
uvx ruff check .         # lint
uvx ruff format --check . # check formatting
uvx ruff format .         # fix formatting
```

CI runs these checks on Python 3.10-3.12, plus shellcheck on shell scripts.

### Manual Testing

To test the plugin locally without installing:

```bash
claude --plugin-dir . --debug
```

This loads the plugin from the current directory and writes debug logs to `~/.claude/debug/`. After running a command like `/generate-report`, you can provide the log file to Claude for analysis:

```
look at the debug log: ~/.claude/debug/<session-id>.txt
```
