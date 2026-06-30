#!/usr/bin/env bash
# Verify `npx plugins add` installs the asta plugins into a coding agent's
# native plugin system.
#
# No API auth is required: this only installs the plugins (a file operation)
# and checks that the expected skill files and hooks landed in the agent's
# plugin cache.
#
# Usage: scripts/verify-plugin-install.sh <claude-code|codex>
#
# The target's CLI binary (`claude` or `codex`) must be on PATH so the plugins
# CLI can detect it. Everything is written under a throwaway HOME.
set -euo pipefail

TARGET="${1:?usage: verify-plugin-install.sh <claude-code|codex>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# @latest is what `npx plugins add` gives users — green means users can install.
# Override PLUGINS_CLI to pin if an upstream release regresses.
PLUGINS_CLI="${PLUGINS_CLI:-plugins@latest}"

# Expected = the skills actually in the plugin's source dir — single source of
# truth, auto-adjusts when skills are added/removed.
expected_count() {
  find "$REPO_ROOT/plugins/$1/skills" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' '
}

TMPHOME="$(mktemp -d)"
trap 'rm -rf "$TMPHOME"' EXIT

echo "==> Installing asta plugins into '$TARGET' (HOME=$TMPHOME)"
HOME="$TMPHOME" npx -y "$PLUGINS_CLI" add "$REPO_ROOT" --target "$TARGET" --yes

case "$TARGET" in
  claude-code)
    CACHE="$TMPHOME/.claude/plugins/cache"
    REGISTRATION="$TMPHOME/.claude/plugins/installed_plugins.json"
    ;;
  codex)
    CACHE="$TMPHOME/.codex/plugins/cache"
    REGISTRATION="$TMPHOME/.codex/config.toml"
    ;;
  *)
    echo "unknown target: $TARGET" >&2
    exit 2
    ;;
esac

echo "==> Verifying installation under $CACHE"

# Count skill directories in an installed plugin's cache. The whole plugin dir
# is copied to <cache>/<marketplace>/<plugin>/<versionKey>/, so match the
# plugin segment exactly.
count_installed_skills() {
  local plugin="$1" skills_dir
  skills_dir="$(find "$CACHE" -type d -path "*/$plugin/*/skills" -print -quit 2>/dev/null || true)"
  if [ -z "$skills_dir" ]; then
    echo 0
    return
  fi
  find "$skills_dir" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' '
}

fail=0
for plugin in asta-tools; do
  expect="$(expected_count "$plugin")"
  got="$(count_installed_skills "$plugin")"
  if [ "$got" = "$expect" ]; then
    echo "  ✓ $plugin: $got skills installed"
  else
    echo "  ✗ $plugin: expected $expect skills, found $got" >&2
    fail=1
  fi
  # Hooks ship with the plugin — confirm hooks.json landed in the install too.
  hooks_json="$(find "$CACHE" -type f -path "*/$plugin/*/hooks/hooks.json" -print -quit 2>/dev/null || true)"
  if [ -n "$hooks_json" ]; then
    echo "  ✓ $plugin: hooks installed"
  else
    echo "  ✗ $plugin: hooks.json missing" >&2
    fail=1
  fi
done

# Sanity-check that the agent recorded the plugins in its own registry.
if [ -f "$REGISTRATION" ] && grep -q "asta" "$REGISTRATION"; then
  echo "  ✓ registered in $(basename "$REGISTRATION")"
else
  echo "  ✗ no asta entry in $REGISTRATION" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "==> FAILED: plugin install verification for '$TARGET'" >&2
  exit 1
fi
echo "==> OK: asta-tools installed into '$TARGET'"
