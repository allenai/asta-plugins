# Developer Guide

This guide covers everyday contributor workflows: setup, the dev loop, and releases.
For one-off tasks (extending the CLI, adding skills, updating passthrough tools), see
the linked docs.

## Overview

Asta is a CLI-first package (`src/asta/`) with three Claude Code plugins
(`plugins/asta-tools`, `plugins/asta-flows`, `plugins/asta-dev`). The CLI is a
thin Click wrapper around stdlib-only core API clients; the plugins ship the skills
and hooks that drive agents to call the CLI. Read the source tree directly for the
current layout — `pyproject.toml` is the source of truth for build config.

Design rules worth knowing before you change code:

- Core API clients (`asta.literature.client`, `asta.papers.client`) stay stdlib-only.
- Click commands stay thin — logic belongs in the client classes.
- New external-tool integrations go through the passthrough system
  (`asta.utils.passthrough` + `passthrough.conf`), not bespoke wrappers.

## Development Setup

Prerequisites: Python 3.11+, `uv`, `make`, and Node.js 20+ / `npx`
(skill-discovery tests are skipped if `npx` is missing).

```bash
git clone https://github.com/allenai/asta-plugins.git
cd asta-plugins
make install
```

`make install` creates `.venv/bin/asta` as an editable install — Python changes are
picked up immediately. Run `make help` to see every available target.

To use the dev `asta` from other directories, either invoke
`/path/to/asta-plugins/.venv/bin/asta` directly or activate `.venv`. For coding
agents that invoke bare `asta`, add a shell alias that prepends the venv to `PATH`:

```bash
alias claude-asta='PATH="/path/to/asta-plugins/.venv/bin:$PATH" claude --plugin-dir /path/to/asta-plugins/plugins/asta-tools'
```

If a global `asta` plugin is installed, disable it via Claude Code settings while
developing with `--plugin-dir` to avoid loading skills twice.

**What needs a reinstall:**

| Changed                          | Action                                          |
|----------------------------------|-------------------------------------------------|
| Python files under `src/asta/`   | None — editable install                         |
| `pyproject.toml` (deps, scripts) | `make install`                                  |
| Skills or hooks under `plugins/` | Restart your `claude-asta` session              |

## Dev Loop

```bash
make check     # format-check + lint + unit tests — run before every commit
make ci        # full CI: format-check + lint + all tests + skill validation
make test      # all tests (also: test-unit, test-integration, test-coverage)
make format    # auto-fix formatting
```

`make ci` is what GitHub Actions runs. Get it green before opening a PR.

### PR checklist

- One feature/fix per PR; include tests.
- Update `CHANGELOG.md`.
- Update README.md if user-visible behavior changes.
- `make ci` passes.

## Release Process

The version lives in three places:

- `src/asta/__init__.py` — `__version__`
- `pyproject.toml` — `version`
- `.claude-plugin/marketplace.json` — `plugins[].version`

`make set-version` keeps them in sync; `make push-version-tag` enforces it.

**Every release:**

1. `make set-version VERSION=x.y.z`
2. `git diff` — sanity-check the version bump.
3. `make ci` — must be green.
4. Commit and push the version bump:
   ```bash
   git add -A && git commit -m "chore: bump version to x.y.z" && git push
   ```
5. `make push-version-tag` — verifies all three version files match, fails if the
   tag already exists, then creates and pushes the git tag. Prints a URL for the
   GitHub release page.
6. Open the URL, add release notes, publish the release. This triggers
   `docker.yml`, which publishes `ghcr.io/allenai/asta:<tag>`.
7. *(Optional)* Publish to PyPI: `make publish` (or `make publish-test` for
   TestPyPI).

If `push-version-tag` reports a version mismatch, rerun `make set-version` to
resync — don't hand-edit one file.

## Specific Workflows

- **Extending the CLI** (commands, API endpoints, dependencies, passthrough tools) — [docs/cli-commands.md](docs/cli-commands.md)
- **Authoring skills and hooks** — [docs/plugins.md](docs/plugins.md)
- **Docker image (build, manual test, troubleshooting)** — [docs/docker.md](docs/docker.md)
