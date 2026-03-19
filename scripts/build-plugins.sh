#!/usr/bin/env bash
# Generate self-contained Claude Code plugin directories in plugins/.
# Edit skills/ — never edit plugins/ directly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGINS_DIR="$REPO_ROOT/plugins"

# Derive default vs preview from SKILL.md frontmatter.
# A skill is default unless its SKILL.md contains "internal: true".
DEFAULT_SKILLS=()
ALL_SKILLS=()
for d in "$REPO_ROOT"/skills/*/; do
  name="$(basename "$d")"
  ALL_SKILLS+=("$name")
  if ! grep -q "internal: true" "$d/SKILL.md" 2>/dev/null; then
    DEFAULT_SKILLS+=("$name")
  fi
done

build_plugin() {
  local name="$1"
  shift
  local skill_dirs=("$@")
  local dest="$PLUGINS_DIR/$name"

  rm -rf "$dest"
  mkdir -p "$dest/skills"

  # Copy skills
  for skill in "${skill_dirs[@]}"; do
    cp -R "$REPO_ROOT/skills/$skill" "$dest/skills/$skill"
  done

  # Copy hooks
  if [ -d "$REPO_ROOT/hooks" ]; then
    cp -R "$REPO_ROOT/hooks" "$dest/hooks"
  fi

  echo "Built $name with ${#skill_dirs[@]} skills"
}

build_plugin "asta" "${DEFAULT_SKILLS[@]}"
build_plugin "asta-preview" "${ALL_SKILLS[@]}"

echo "Done. Plugins written to plugins/"
