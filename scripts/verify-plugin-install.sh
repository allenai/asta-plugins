#!/usr/bin/env bash
# Verify `npx plugins add` installs the asta plugins into a coding agent's
# native plugin system.
#
# No API auth is required to check installed files or capture the skills prompt.
#
# Verify complete model-visible descriptions for asta-tools, asta-assistant,
# and asta-dev together. This test includes asta-dev even though it is optional
# for users (needs uv and Python 3).
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
if ! PYTHON3="$(command -v python3)"; then
  echo "  ✗ python3 is required to verify the skills prompt" >&2
  exit 1
fi
if ! command -v uv >/dev/null; then
  echo "  ✗ uv is required to verify the skills prompt" >&2
  exit 1
fi

# Expected = the skills actually in the plugin's source dir — single source of
# truth, auto-adjusts when skills are added/removed.
expected_count() {
  find "$REPO_ROOT/plugins/$1/skills" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' '
}

TMPHOME="$(mktemp -d)"
trap 'rm -rf "$TMPHOME"' EXIT

# Stage the three prompt-test plugins together so asta-flows does not
# consume the skill budget.
PROMPT_SOURCE="$TMPHOME/prompt-source"
PROMPT_HOME="$TMPHOME/prompt-home"
mkdir -p "$PROMPT_HOME"
"$PYTHON3" - "$REPO_ROOT" "$PROMPT_SOURCE" asta-tools asta-assistant asta-dev <<'PYTHON'
import json
import shutil
import sys
from pathlib import Path

source, fixture = map(Path, sys.argv[1:3])
manifest = Path(".claude-plugin/marketplace.json")
data = json.loads((source / manifest).read_text(encoding="utf-8"))
by_name = {plugin["name"]: plugin for plugin in data["plugins"]}
for name in sys.argv[3:]:
    if name not in by_name:
        sys.exit(f"  ✗ {name}: required in {manifest} for the skills prompt check")
    location = by_name[name].get("source")
    if (
        not isinstance(location, str)
        or not location.startswith("./")
        or not (source / location).resolve().is_relative_to(source)
    ):
        sys.exit(f"  ✗ {name}: expected a local plugin source in {manifest}")
data["plugins"] = [by_name[name] for name in sys.argv[3:]]
(fixture / manifest).parent.mkdir(parents=True)
(fixture / manifest).write_text(json.dumps(data), encoding="utf-8")
for plugin in data["plugins"]:
    shutil.copytree(source / plugin["source"], fixture / plugin["source"])
PYTHON

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

echo "==> Verifying the skills '$TARGET' shows to the model"
HOME="$PROMPT_HOME" CODEX_HOME="$PROMPT_HOME/.codex" npm_config_cache="$TMPHOME/.npm" \
  npx -y "$PLUGINS_CLI" add "$PROMPT_SOURCE" --target "$TARGET" --yes
PROMPT_JSON="$TMPHOME/prompt.json"
capture_prompt() {
  case "$TARGET" in
    codex)
      (cd "$PROMPT_HOME" && env -i PATH="$PATH" HOME="$PROMPT_HOME" \
        CODEX_HOME="$PROMPT_HOME/.codex" codex debug prompt-input)
      ;;
    claude-code)
      "$PYTHON3" "$REPO_ROOT/scripts/capture-claude-skill-prompt.py" "$PROMPT_HOME"
      ;;
  esac
}
if capture_prompt >"$PROMPT_JSON"; then
  uv run --no-project --python "$PYTHON3" --with 'PyYAML==6.0.3' \
    python "$REPO_ROOT/scripts/check-skill-prompt.py" "$TARGET" "$PROMPT_JSON" \
    --source "$PROMPT_SOURCE" || fail=1
else
  echo "  ✗ failed to capture the '$TARGET' skills prompt" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "==> FAILED: plugin install verification for '$TARGET'" >&2
  exit 1
fi
echo "==> OK: asta-tools + asta-flows + asta-assistant + asta-dev installed into '$TARGET'"
