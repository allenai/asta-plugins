---
name: asta-cli
description: "Install or update the `asta` CLI to the version pinned by this plugin. Invoke whenever `asta` is not on PATH (e.g. `command not found` for `asta`) or when a subcommand/flag appears missing — that signals a stale install needing an update."
allowed-tools: Bash(command -v asta) Bash(asta --version) Bash(uv tool install*)
---

# Asta CLI Installer

Installs the `asta` CLI for agents that don't install it automatically via a plugin hook.

## When to invoke

- `asta` is not on `PATH` (e.g., `command -v asta` returns nothing, or running `asta ...` reports "command not found")
- A subcommand, option, or output field that should exist according to another skill is missing — that signals an outdated install

## Install or update

**Prerequisites:** Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
PLUGIN_VERSION=0.19.1
INSTALL_URL="git+https://github.com/allenai/asta-plugins.git@v$PLUGIN_VERSION"

if ! command -v asta &> /dev/null; then
  echo "📦 Installing Asta CLI $PLUGIN_VERSION..."
  uv tool install "$INSTALL_URL"
else
  CLI_VERSION=$(asta --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
  if [ "$CLI_VERSION" != "$PLUGIN_VERSION" ]; then
    echo "🔄 Updating Asta CLI from $CLI_VERSION to $PLUGIN_VERSION..."
    uv tool install --force "$INSTALL_URL"
  fi
fi
```

If `asta` is still not on PATH after install, run `uv tool update-shell` (or open a new shell) so `~/.local/bin` is on PATH.

## After install

Re-run the original command. If it still fails, the problem is not the CLI version — surface the actual error to the user instead of reinstalling again.
