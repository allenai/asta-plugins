# Developer Guide

This guide is for contributors and developers who want to understand the architecture, add new features, or develop Claude Code plugins.

## Architecture Overview

Asta uses a CLI-first architecture with Claude Code plugin integration:

```
src/asta/                      # Main CLI package
├── __init__.py                # Package metadata (__version__)
├── cli.py                     # Click command groups
├── core/
│   ├── __init__.py
│   └── client.py              # AstaPaperFinder API client (stdlib only)
├── documents/
│   ├── __init__.py
│   └── passthrough.py         # `asta documents` pass-through to asta-documents CLI
├── literature/
│   ├── __init__.py
│   └── find.py                # `asta literature find` command
└── papers/
    ├── __init__.py
    ├── client.py              # SemanticScholarClient (stdlib only)
    ├── get.py                 # `asta papers get` command
    ├── search.py              # `asta papers search` command
    ├── citations.py           # `asta papers citations` command
    └── author.py              # `asta papers author` commands

skills/                        # Claude Code skill definitions
hooks/                         # Claude Code permission hooks
.claude-plugin/plugin.json     # Claude Code plugin manifest
```

### Design Principles

1. **Core is dependency-free**: `asta.core.client` and `asta.papers.client` use only stdlib (json, urllib, time, etc.)
2. **CLI layer is thin**: Click commands wrap the core clients
3. **Pass-through commands**: `asta documents` is a pass-through to the external `asta-documents` CLI, which is auto-installed on first use
4. **Claude Code integration**: Uses the CLI via Bash tool for portability

## Development Setup

### Prerequisites

- Python 3.10+
- `uv` (recommended) or `pip`

### Install for Development

```bash
git clone https://github.com/allenai/asta-plugins.git
cd asta-plugins

# Install with test dependencies
uv sync --extra test

# Or with pip
pip install -e ".[test]"
```

### Run Tests

```bash
# Run all tests
uv run --extra test pytest -v

# Run specific test file
uv run --extra test pytest tests/test_cli.py -v

# Run with coverage
uv run --extra test pytest --cov=src/asta --cov-report=html
```

### Test the CLI

```bash
# Run directly from source
uv run python -m asta.cli --version
uv run python -m asta.cli literature find "test query" --timeout 60

# Test documents pass-through (will auto-install asta-documents on first use)
uv run python -m asta.cli documents --help
uv run python -m asta.cli documents list

# Or install as tool and test
uv tool install .
asta --version
asta literature find "test query"
asta documents list
```

### Linting and Formatting

```bash
# Check code style
uvx ruff check .

# Fix formatting
uvx ruff format .

# Check formatting without changes
uvx ruff format --check .
```

## Adding New Commands

### 1. Create the command module

Add a new file in `src/asta/literature/` (or create a new subpackage):

```python
# src/asta/literature/analyze.py
import click
from asta.core import AstaPaperFinder

@click.command()
@click.argument("widget_id")
@click.option("--format", type=click.Choice(["json", "markdown"]), default="json")
def analyze(widget_id: str, format: str):
    """Analyze papers from a previous search."""
    # Implementation here
    pass
```

### 2. Register in cli.py

```python
# src/asta/cli.py
from asta.literature.analyze import analyze

literature.add_command(analyze)
```

### 3. Add tests

```python
# tests/test_analyze.py
from click.testing import CliRunner
from asta.cli import cli

def test_analyze_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["literature", "analyze", "widget-123"])
    assert result.exit_code == 0
```

### 4. Update documentation

Update README.md and this DEVELOPER.md with the new command.

## Core API Clients

### AstaPaperFinder

The `AstaPaperFinder` client in `src/asta/core/client.py` handles paper finder API interactions.

```python
from asta.core import AstaPaperFinder

client = AstaPaperFinder()

# Simple blocking search
result = client.find_papers("query", timeout=300)
# Returns: {widget_id, file_path, paper_count}

# Non-blocking start
thread_id = client.start_search("query")
widget_id = client.get_widget_id(thread_id)
results = client.poll_for_results(widget_id, timeout=300)
```

### SemanticScholarClient

The `SemanticScholarClient` in `src/asta/papers/client.py` handles Semantic Scholar API interactions.

```python
from asta.papers.client import SemanticScholarClient

client = SemanticScholarClient()  # Uses ASTA_TOOL_KEY env var if available

# Get paper details
paper = client.get_paper("ARXIV:2005.14165", fields="title,abstract,authors")

# Search papers
results = client.search_papers("transformers", limit=20, year="2023-")

# Get citations
citations = client.get_paper_citations("ARXIV:2005.14165", limit=50)

# Author search
authors = client.search_author("Yoav Goldberg")
papers = client.get_author_papers("1741101", limit=50)
```

### Adding New API Endpoints

1. Add a method to the appropriate client class
2. Keep it dependency-free (stdlib only)
3. Add tests in `tests/test_client.py` or `tests/test_papers_cli.py`
4. Create CLI commands to expose the functionality

## Claude Code Plugin Development

### Skill Files

Skills are markdown files in `skills/<skill-name>/SKILL.md`:

```markdown
---
name: Skill Name
description: When to use this skill
allowed-tools:
  - Bash(asta *)
  - Read(*)
---

# Skill Name

Instructions and examples...
```

### Hooks

Hooks in `hooks/` are bash scripts that can auto-approve tool usage:

```bash
#!/bin/bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

if [[ "$COMMAND" == asta* ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
  exit 0
fi

echo '{}'
```

Register hooks in `hooks/hooks.json`:

```json
{
  "user-prompt-submit-hook": "hooks/session-start.sh",
  "tool-use-pre-hook": [
    "hooks/approve-asta-bash.sh",
    "hooks/approve-asta-files.sh"
  ]
}
```

### Testing Claude Code Integration

```bash
# Run Claude Code with local plugin
claude --plugin-dir . --debug

# In Claude, test skills naturally
# Skills activate automatically based on what you ask
Find papers on machine learning
Generate a literature report on transformers
Get details for arXiv:2005.14165

# Check debug logs
cat ~/.claude/debug/<session-id>.txt
```

## Project Structure Details

### Source Layout (src/)

Uses PyPA recommended src/ layout:

- Prevents accidental imports during development
- Better build isolation
- Clear separation between source and tests

### Build System

Uses `hatchling` as build backend:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/asta"]
```

## Release Process

### Version Bumping

Update version in `src/asta/__init__.py`:

```python
__version__ = "0.3.0"
```

Also update in `.claude-plugin/plugin.json` if needed.

### Building Distribution

```bash
# Build package
uv build

# Creates dist/asta-0.3.0.tar.gz and dist/asta-0.3.0-*.whl
```

### Publishing to PyPI

```bash
# Install twine
uv pip install twine

# Upload to PyPI
uv run twine upload dist/*

# Or to TestPyPI first
uv run twine upload --repository testpypi dist/*
```

### GitHub Release

1. Tag the release: `git tag v0.3.0`
2. Push tag: `git push origin v0.3.0`
3. Create GitHub release with changelog

## Testing Strategy

### Unit Tests

- `tests/test_client.py`: Core API client tests
- `tests/test_cli.py`: CLI command tests using Click's CliRunner
- Mock external API calls

### Integration Tests

- `tests/test_integration.py`: End-to-end CLI tests
- `tests/test_paper_finder.py`: Backward compatibility tests
- `tests/test_hooks.py`: Hook script tests

### Claude Code Tests

- `tests/test_config.py`: Plugin manifest validation

### Running Specific Test Categories

```bash
# Just core tests
uv run --extra test pytest tests/test_client.py tests/test_cli.py

# Just integration
uv run --extra test pytest tests/test_integration.py

# Just Claude Code plugin
uv run --extra test pytest tests/test_config.py
```

## Common Development Tasks

### Adding a New Dependency

Only add dependencies if absolutely necessary:

1. Add to `dependencies` in `pyproject.toml`
2. Run `uv sync`
3. Update tests to verify it works
4. Document why it's needed

Core (`asta.core`) should remain dependency-free.

### Updating API Endpoints

If Asta's API changes:

1. Update `AstaPaperFinder` in `src/asta/core/client.py`
2. Add/update tests in `tests/test_client.py`
3. Update documentation examples
4. Consider backward compatibility

### Debugging

```bash
# Enable Python warnings
PYTHONWARNINGS=default uv run python -m asta.cli literature find "test"

# Run with Python debugger
uv run python -m pdb -m asta.cli literature find "test"

# Check what's installed
uv pip list
```

## Contributing Guidelines

### Before Submitting a PR

1. Run all tests: `uv run --extra test pytest -v`
2. Check formatting: `uvx ruff format --check .`
3. Check linting: `uvx ruff check .`
4. Update documentation if adding features
5. Add tests for new functionality

### PR Guidelines

- One feature/fix per PR
- Include tests
- Update CHANGELOG.md
- Keep commits focused and well-described
- Reference any related issues

### Code Style

- Follow PEP 8 (enforced by ruff)
- Use type hints where helpful
- Keep functions focused and short
- Document complex logic with comments
- Add docstrings to public APIs

## Getting Help

- Open an issue: https://github.com/allenai/asta-plugins/issues
- Check existing issues and discussions
- Read the code - it's designed to be understandable
