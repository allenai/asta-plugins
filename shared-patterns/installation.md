---
name: installation
description: Standard install/upgrade block for the `asta` CLI that every Asta skill depends on.
---

# Installation

Every Asta skill invokes the `asta` CLI. Before running any `asta ...` command for the first time in a session — or any time the user reports a missing command or version mismatch — run the block below. It is idempotent: if `asta` is already at the expected version, it does nothing.

```bash
# Install/reinstall at the correct version
PLUGIN_VERSION=0.17.1
if [ "$(asta --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" != "$PLUGIN_VERSION" ]; then
  uv tool install --force git+https://github.com/allenai/asta-plugins.git@v$PLUGIN_VERSION
fi
```

**Prerequisites:** Python 3.11+ and the [uv package manager](https://docs.astral.sh/uv/).

## Notes for skill authors

- The `PLUGIN_VERSION` value is kept in sync with `src/asta/__init__.py`, `pyproject.toml`, and `.claude-plugin/marketplace.json` by `scripts/manage-version.py`. Use `make set-version VERSION=x.y.z` — do not edit the version here by hand.
- Skills that need *additional* setup beyond this block (cloud credentials, auth login, extra dependencies) should keep their own `## Installation` or `## Setup` section and reference this file for the CLI install step.
