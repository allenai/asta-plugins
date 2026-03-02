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
├── utils/
│   ├── __init__.py
│   └── passthrough.py         # Generic passthrough utility for external tools
├── documents/
│   ├── __init__.py
│   └── passthrough.py         # `asta documents` pass-through to asta-documents CLI
├── experiment/
│   ├── __init__.py
│   └── passthrough.py         # `asta experiment` pass-through to panda CLI
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
3. **Generic passthrough architecture**: `asta.utils.passthrough` provides reusable utilities for external tool integration
   - `ensure_tool_installed()`: Checks for tool, auto-installs if missing
   - `create_passthrough_command()`: Factory function for creating passthrough commands
4. **Pass-through commands**: Commands that delegate to external tools, auto-installed on first use
   - `asta documents` → `asta-documents` CLI (document metadata management)
   - `asta experiment` → `panda` CLI (computational experiments)
   - Version pinning: Each passthrough defines a version constant (e.g., `ASTA_DOCUMENTS_VERSION`, `PANDA_VERSION`)
   - Future: will install from PyPI instead of git
5. **Claude Code integration**: Uses the CLI via Bash tool for portability

## Development Setup

### Prerequisites

- Python 3.10+
- `uv` (for running commands)
- `make` (for development tasks)

### Quick Start

A Makefile is provided for all common development tasks:

```bash
make help     # Show all available targets
make install  # Install with test dependencies
make test     # Run all tests
make lint     # Check code style
make format   # Auto-fix formatting
make check    # Quick pre-commit check (format + lint + unit tests)
make ci       # Full CI check (format + lint + all tests)
make build    # Build distribution packages
make clean    # Remove build artifacts
```

### Install for Development

```bash
git clone https://github.com/allenai/asta-plugins.git
cd asta-plugins
make install
```

### Run Tests

```bash
make test              # Run all tests
make test-unit         # Run unit tests only
make test-integration  # Run integration tests only
make test-coverage     # Run with HTML coverage report
```

### Test the CLI

```bash
# Install the package in development mode
make install

# Run directly from source
uv run python -m asta.cli --version
uv run python -m asta.cli literature find "test query" --timeout 60

# Test documents pass-through (will auto-install asta-documents on first use)
uv run python -m asta.cli documents --help
uv run python -m asta.cli documents list
```

### Linting and Formatting

```bash
make lint          # Check code style
make format        # Auto-fix formatting
make format-check  # Check formatting without changes
make check         # Quick pre-commit check (format-check + lint + unit tests)
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
make build  # Cleans and builds distribution packages
```

Creates `dist/asta-VERSION.tar.gz` and `dist/asta-VERSION-*.whl`

### Publishing to PyPI

```bash
make publish       # Build and publish to PyPI
make publish-test  # Build and publish to TestPyPI
```

### GitHub Release

To create a GitHub release (automatically uses version from code):

```bash
make release  # Uses version from src/asta/__init__.py
# Then create GitHub release at the URL provided
```

The release target will fail if the git tag already exists, preventing accidental overwrites.

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
make test-unit         # Core tests (client, cli)
make test-integration  # Integration and compatibility tests
```

## Common Development Tasks

### Adding a New Dependency

Only add dependencies if absolutely necessary:

1. Add to `dependencies` in `pyproject.toml`
2. Run `make install` to sync dependencies
3. Update tests to verify it works
4. Document why it's needed

Core (`asta.core`) should remain dependency-free.

### Updating API Endpoints

If Asta's API changes:

1. Update `AstaPaperFinder` in `src/asta/core/client.py`
2. Add/update tests in `tests/test_client.py`
3. Update documentation examples
4. Consider backward compatibility

### Adding a New Passthrough Command

To add a new external tool as an `asta` passthrough command:

1. **Create the passthrough module:**
   ```python
   # src/asta/newtool/__init__.py
   from asta.newtool.passthrough import newtool
   __all__ = ["newtool"]

   # src/asta/newtool/passthrough.py
   from asta.utils.passthrough import create_passthrough_command

   NEWTOOL_VERSION = "v1.0.0"  # Pin to specific version

   newtool = create_passthrough_command(
       tool_name="newtool-cli",              # Executable name
       install_source="git+https://github.com/org/newtool",
       version=NEWTOOL_VERSION,
       command_name="newtool",               # asta subcommand name
       friendly_name="NewTool",              # Display name
       docstring="Description for --help"
   )
   ```

2. **Register in CLI:**
   ```python
   # src/asta/cli.py
   from asta.newtool import newtool
   cli.add_command(newtool)
   ```

3. **Add tests:**
   ```python
   # tests/test_cli.py
   class TestNewToolCommand:
       def test_newtool_version_constant(self):
           from asta.newtool.passthrough import NEWTOOL_VERSION
           assert isinstance(NEWTOOL_VERSION, str)
           assert len(NEWTOOL_VERSION) > 0

       def test_newtool_passthrough_when_installed(self, runner, tmp_path):
           # Test passthrough behavior
           ...
   ```

4. **Create skill (optional):**
   ```markdown
   # skills/newtool/SKILL.md
   ---
   name: NewTool Skill
   description: When to use this skill
   allowed-tools:
     - Bash(asta newtool *)
   ---

   Use `asta newtool` to invoke the external tool...
   ```

5. **Update documentation:**
   - Add to README.md skill list
   - Document in DEVELOPER.md

### Updating Passthrough Tool Versions

When a new version of a passthrough tool is released:

**For asta-documents:**
1. Update `ASTA_DOCUMENTS_VERSION` in `src/asta/documents/passthrough.py`
   ```python
   ASTA_DOCUMENTS_VERSION = "v0.2.0"  # Change to new tag
   ```
2. Test the installation works:
   ```bash
   # Uninstall current version
   uv tool uninstall asta-documents
   # Test auto-installation with new version
   uv run python -m asta.cli documents --help
   ```
3. Update release notes mentioning the new version

**For panda (experiment command):**
1. Update `PANDA_VERSION` in `src/asta/experiment/passthrough.py`
   ```python
   PANDA_VERSION = "v1.0.0"  # Change to new tag
   ```
2. Test similarly:
   ```bash
   uv tool uninstall panda
   uv run python -m asta.cli experiment --help
   ```

**Note**: In the future, when these tools are available on PyPI, update the installation source in the passthrough files:
```python
# Change from:
install_source="git+https://github.com/org/repo"

# To:
install_source="package-name"  # Will use PyPI
```

### Debugging

```bash
# Run with Python debugger
uv run python -m pdb -m asta.cli literature find "test"

# Enable Python warnings
PYTHONWARNINGS=default uv run python -m asta.cli literature find "test"
```

## Contributing Guidelines

### Before Submitting a PR

Run all checks at once:
```bash
make ci  # Runs format-check, lint, and all tests
```

Or individually:
1. Run all tests: `make test`
2. Check formatting: `make format-check`
3. Check linting: `make lint`
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
