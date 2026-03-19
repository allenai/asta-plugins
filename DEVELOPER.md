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
│   ├── config.py              # Configuration management using HOCON
│   ├── passthrough.conf       # Passthrough tool configurations (HOCON format)
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

1. **Core clients are dependency-free**: `asta.literature.client` and `asta.papers.client` use only stdlib (json, urllib, time, etc.)
2. **CLI layer is thin**: Click commands wrap the core clients
3. **Generic passthrough architecture**: `asta.utils.passthrough` provides reusable utilities for external tool integration
   - `ensure_tool_installed()`: Checks for tool, auto-installs if missing
   - `create_passthrough_command()`: Factory function for creating passthrough commands
4. **Configuration management**: `asta.utils.config` loads passthrough settings from HOCON
   - All passthrough configurations centralized in `src/asta/utils/passthrough.conf`
   - Uses pyhocon for flexible, hierarchical configuration
   - `get_passthrough_config()`: Retrieves settings for specific commands
5. **Pass-through commands**: Commands that delegate to external tools, auto-installed on first use
   - `asta documents` → `asta-documents` CLI (document metadata management)
   - `asta experiment` → `panda` CLI (computational experiments)
   - Configuration: Version pinning, install sources, and other settings in `passthrough.conf`
   - Future: will install from PyPI instead of git
6. **Claude Code integration**: Uses the CLI via Bash tool for portability

## Development Setup

### Prerequisites

- Python 3.11+
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

`make install` creates `.venv/bin/asta` as an editable install — changes to Python source
are picked up immediately, no reinstall needed.

#### Using dev asta from other directories

To use the dev `asta` from any directory, either invoke it directly:

```bash
/path/to/asta-plugins/.venv/bin/asta --help
```

Or activate the venv:

```bash
source /path/to/asta-plugins/.venv/bin/activate
```

If you have a global `asta` installed, it stays unaffected — the venv takes precedence
only while active.

For coding agents like Claude that invoke bare `asta` from arbitrary working directories,
add to `~/.zshrc`:

```bash
alias claude-asta='PATH="/path/to/asta-plugins/.venv/bin:$PATH" claude --plugin-dir /path/to/asta-plugins'
```

The PATH prepend ensures skills resolve `asta` to your local source for that session,
without affecting your global install. If you have the `asta` plugin installed globally,
disable or uninstall it via Claude Code settings while developing to avoid loading it
twice alongside `--plugin-dir`.

#### Picking up changes

| Changed | Action needed |
|---|---|
| Python files (`src/asta/`) | None — editable install |
| `pyproject.toml` (new deps/scripts) | `make install` |
| Skills, hooks, `plugin.json` | Restart `claude-asta` session |

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
from asta.literature.client import AstaPaperFinder

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

The `AstaPaperFinder` client in `src/asta/literature/client.py` handles paper finder API interactions.

```python
from asta.literature import AstaPaperFinder

client = AstaPaperFinder()

# Simple synchronous search using headless endpoint
result = client.find_papers("query", timeout=300)
# Returns: {query, widget, status, timestamp, paper_count}

# With operation mode control
result = client.find_papers(
    "query",
    timeout=300,
    operation_mode="fast",  # "infer", "fast", or "diligent"
    include_full_metadata=True
)
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

The version number is stored in four locations and must be kept in sync:
- `src/asta/__init__.py` - `__version__` variable (Python package version)
- `pyproject.toml` - `version` field (Build system version)
- `.claude-plugin/plugin.json` - `version` field (Plugin manifest for Claude Code)
- `.claude-plugin/marketplace.json` - `plugins[0].version` field (Marketplace listing for `/plugin marketplace add`)

**Note:** Both `.claude-plugin/plugin.json` (individual plugin manifest) and `.claude-plugin/marketplace.json` (marketplace repository listing) are required. The marketplace file allows users to install via `/plugin marketplace add allenai/asta-plugins` in Claude Code.

### Complete Release Workflow

1. **Update version in all files:**
   ```bash
   make set-version VERSION=0.3.0
   ```
   This updates all three version locations atomically.

2. **Review changes:**
   ```bash
   git diff
   ```
   Verify that all three files were updated correctly.

3. **Run full test suite:**
   ```bash
   make ci
   ```
   Ensures all tests pass, code is formatted, and linting is clean.

4. **Commit version bump:**
   ```bash
   git add -A
   git commit -m "chore: bump version to 0.3.0"
   git push
   ```

5. **Create and push version tag:**
   ```bash
   make push-version-tag
   ```
   This command will:
   - Verify all three version files are in sync (fails if they differ)
   - Check that the git tag doesn't already exist
   - Create and push the git tag (e.g., `0.3.0`)
   - Provide a URL to create the GitHub release

6. **Create GitHub release notes:**
   - Visit the URL provided by `make push-version-tag`
   - Add release notes describing changes
   - Publish the release

7. **Publish to PyPI (optional):**
   ```bash
   make publish       # Production PyPI
   make publish-test  # TestPyPI for testing
   ```

### Version Management Commands

**Check current version:**
```bash
make version
```

**Set version in all files:**
```bash
make set-version VERSION=x.y.z
```
- Updates all four version locations atomically
- Fails with error if VERSION parameter is not provided
- Provides suggested commit command after success

**Push version tag:**
```bash
make push-version-tag
```
- Checks version consistency across all four files
- Fails with clear error if versions don't match
- Shows current versions in each file when there's a mismatch
- Creates and pushes git tag if all checks pass
- Fails if git tag already exists (prevents accidental overwrites)

### Version Mismatch Example

If you try to push a version tag with mismatched versions:

```bash
$ make push-version-tag
Checking version consistency...
Error: Version mismatch detected:
  src/asta/__init__.py:              0.3.0
  pyproject.toml:                    0.2.0
  .claude-plugin/plugin.json:        0.2.0
  .claude-plugin/marketplace.json:   0.2.0

Run 'make set-version VERSION=x.y.z' to sync versions
```

### Building Distribution

```bash
make build  # Cleans and builds distribution packages
```

Creates `dist/asta-VERSION.tar.gz` and `dist/asta-VERSION-*.whl`

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

Core API clients (`asta.literature.client`, `asta.papers.client`) should remain dependency-free.

### Updating API Endpoints

If Asta's API changes:

1. Update `AstaPaperFinder` in `src/asta/literature/client.py`
2. Add/update tests in `tests/test_client.py`
3. Update documentation examples
4. Consider backward compatibility

### Adding a New Passthrough Command

To add a new external tool as an `asta` passthrough command:

1. **Add configuration** to `src/asta/utils/passthrough.conf`:
   ```hocon
   passthrough {
     # ... existing configs ...

     newtool {
       tool_name = "newtool-cli"
       install_type = "pypi"  # or "git" or "local"
       install_source = "newtool-package"  # package name, git URL, or filesystem path
       minimum_version = "1.0.0"  # Must be x.y.z format
       command_name = "newtool"
       docstring = "Description for --help"
     }
   }
   ```

   **Installation source types:**
   - `pypi`: Install from PyPI (e.g., `install_source = "package-name"`)
   - `git`: Install from Git repository (e.g., `install_source = "git+https://github.com/user/repo"`)
   - `local`: Install from local filesystem (e.g., `install_source = "/path/to/package"` or `"~/dev/package"`)

2. **Create the passthrough module:**
   ```python
   # src/asta/newtool/__init__.py
   from asta.newtool.passthrough import newtool
   __all__ = ["newtool"]

   # src/asta/newtool/passthrough.py
   from asta.utils.config import get_passthrough_config
   from asta.utils.passthrough import create_passthrough_command

   # Load configuration from passthrough.conf
   config = get_passthrough_config("newtool")

   # Create the passthrough command
   newtool = create_passthrough_command(
       tool_name=config["tool_name"],
       install_type=config["install_type"],
       install_source=config["install_source"],
       minimum_version=config["minimum_version"],
       command_name=config["command_name"],
       docstring=config["docstring"],
   )
   ```

3. **Register in CLI:**
   ```python
   # src/asta/cli.py
   from asta.newtool import newtool
   cli.add_command(newtool)
   ```

4. **Add tests:**
   ```python
   # tests/test_cli.py
   class TestNewToolCommand:
       def test_newtool_config(self):
           from asta.utils.config import get_passthrough_config
           from asta.utils.passthrough import validate_semver

           config = get_passthrough_config("newtool")
           assert config["tool_name"] == "newtool-cli"
           assert config["install_type"] in ("pypi", "git", "local")
           assert validate_semver(config["minimum_version"])

       def test_newtool_passthrough_when_installed(self, runner, tmp_path):
           # Test passthrough behavior
           ...
   ```

5. **Create skill (optional):**
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

The passthrough system automatically enforces minimum version requirements for external tools.

**How it works:**

1. When you run a passthrough command (e.g., `asta documents`), the system:
   - Checks if the tool is installed
   - If installed, runs `tool --version` to check the version
   - Compares with the `minimum_version` specified in `passthrough.conf`
   - Automatically reinstalls **only if the installed version is below the minimum**

2. Version requirements:
   - Must be in semantic version format: `x.y.z` (e.g., `0.1.0`, `1.2.3`)
   - The 'v' prefix is optional when parsing installed versions (both `1.0.0` and `v1.0.0` are accepted)
   - Versions are compared semantically: `1.0.1` > `1.0.0`, `1.1.0` > `1.0.9`, `2.0.0` > `1.99.99`
   - If the installed version is **greater than or equal** to minimum_version, it will be kept (no downgrade)

3. This allows users to:
   - Install newer versions manually and have them respected
   - Get automatic updates only when their version is too old
   - Avoid unnecessary reinstallations on every run

**To require a newer minimum version:**

1. **Update the configuration** in `src/asta/utils/passthrough.conf`:
   ```hocon
   passthrough {
     documents {
       minimum_version = "0.2.0"  # Require at least version 0.2.0
       # ... other settings
     }
     experiment {
       minimum_version = "1.0.0"  # Require at least version 1.0.0
       # ... other settings
     }
   }
   ```

2. **Next time someone runs the command**, it will automatically update if their version is too old:
   ```bash
   # If installed version < 0.2.0, will reinstall
   # If installed version >= 0.2.0, will use existing installation
   asta documents --help
   asta experiment --help
   ```

3. **Update release notes** mentioning the new minimum version requirement

**Switching installation sources:**

When a tool becomes available on PyPI, update `passthrough.conf`:
```hocon
# Change from Git:
install_type = "git"
install_source = "git+https://github.com/org/repo"

# To PyPI:
install_type = "pypi"
install_source = "package-name"
```

For local development:
```hocon
# Use local installation:
install_type = "local"
install_source = "~/dev/my-package"
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
