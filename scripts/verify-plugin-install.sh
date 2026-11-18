#!/usr/bin/env bash
# Verify `npx plugins add` installs the asta plugins into a coding agent's
# native plugin system.
#
# No API auth is required: this only installs the plugins (a file operation)
# and checks that the expected skill files and hooks landed in the agent's
# plugin cache.
#
# For codex it also renders the model-visible prompt and checks every skill is
# listed with its full description (needs uv and Python 3).
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
HOME="$TMPHOME" CODEX_HOME="$TMPHOME/.codex" \
  npx -y "$PLUGINS_CLI" add "$REPO_ROOT" --target "$TARGET" --yes

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
for plugin in asta-tools asta-flows asta-assistant asta-dev; do
  expect="$(expected_count "$plugin")"
  got="$(count_installed_skills "$plugin")"
  if [ "$got" = "$expect" ]; then
    echo "  ✓ $plugin: $got skills installed"
  else
    echo "  ✗ $plugin: expected $expect skills, found $got" >&2
    fail=1
  fi
  # Only check hooks for plugins that ship them in source.
  if [ -d "$REPO_ROOT/plugins/$plugin/hooks" ]; then
    hooks_json="$(find "$CACHE" -type f -path "*/$plugin/*/hooks/hooks.json" -print -quit 2>/dev/null || true)"
    if [ -n "$hooks_json" ]; then
      echo "  ✓ $plugin: hooks installed"
    else
      echo "  ✗ $plugin: hooks.json missing" >&2
      fail=1
    fi
  fi
done

# Sanity-check that the agent recorded the plugins in its own registry.
if [ -f "$REGISTRATION" ] && grep -q "asta" "$REGISTRATION"; then
  echo "  ✓ registered in $(basename "$REGISTRATION")"
else
  echo "  ✗ no asta entry in $REGISTRATION" >&2
  fail=1
fi

# Codex silently drops or shortens skills that overflow its skills prompt
# budget, so check what the model would actually be shown.
if [ "$TARGET" = codex ]; then
  echo "==> Verifying the skills Codex shows to the model"
  PROMPT_JSON="$TMPHOME/prompt-input.json"
  if ! PYTHON3="$(command -v python3)"; then
    echo "  ✗ python3 is required to verify the Codex skills prompt" >&2
    fail=1
  elif (cd "$TMPHOME" && HOME="$TMPHOME" CODEX_HOME="$TMPHOME/.codex" codex debug prompt-input) >"$PROMPT_JSON"; then
    uv run --no-project --python "$PYTHON3" --with 'PyYAML==6.0.3' \
      python "$REPO_ROOT/scripts/check-codex-skill-prompt.py" "$PROMPT_JSON" || fail=1
  else
    echo "  ✗ codex debug prompt-input failed" >&2
    fail=1
  fi
fi

if [ "$fail" -ne 0 ]; then
  echo "==> FAILED: plugin install verification for '$TARGET'" >&2
  exit 1
fi
echo "==> OK: asta-tools + asta-flows asta-assistant + asta-dev installed into '$TARGET'"
