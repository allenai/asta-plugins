#!/usr/bin/env bash
# Generate the `asta` (core) plugin from the canonical `asta-preview` plugin.
#
# Layout:
#   plugins/asta-preview/  -- CANONICAL. All skills + hooks live here; edit here.
#   plugins/asta/          -- GENERATED. The subset of skills that are NOT
#                             marked `internal` in their SKILL.md frontmatter.
#
# The installers used by Claude Code and Codex (`npx plugins add`) copy a
# plugin's directory wholesale and do not filter skills by frontmatter, so the
# core-only `asta` plugin must exist as its own directory. Only that subset is
# duplicated; `asta-preview` is never a copy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO_ROOT/plugins/asta-preview"
DEST="$REPO_ROOT/plugins/asta"

# Core skills = those whose SKILL.md frontmatter does NOT set `internal: true`.
core_skills=()
for d in "$SRC"/skills/*/; do
  name="$(basename "$d")"
  if ! grep -q "internal: true" "$d/SKILL.md" 2>/dev/null; then
    core_skills+=("$name")
  fi
done

rm -rf "$DEST"
mkdir -p "$DEST/skills"

for skill in "${core_skills[@]}"; do
  cp -R "$SRC/skills/$skill" "$DEST/skills/$skill"
done

cp -R "$SRC/hooks" "$DEST/hooks"

# Plugin name/description/version come from .claude-plugin/marketplace.json
# (the single metadata source) — no per-plugin plugin.json is generated.
echo "Generated plugins/asta with ${#core_skills[@]} core skills (from plugins/asta-preview)"
