#!/usr/bin/env bash
# copy-transcripts.sh — copy coding-agent conversation transcripts for a
# project into a destination directory, organized by agent.
#
# Detects transcripts from three coding agents (Claude Code, Codex CLI, Cursor)
# and copies any that match the given project directory. Each agent's files
# land in their own subdirectory of DEST_DIR.
#
# Usage:
#   scripts/copy-transcripts.sh PROJECT_DIR DEST_DIR
#
# Where:
#   PROJECT_DIR — absolute path to the user's project (cwd at the time of work)
#   DEST_DIR    — directory to write transcripts into (created if missing).
#                 Subdirectories created: claude-code/, codex/, cursor/
#
# Output (stdout, key: value lines, one block per agent):
#   agent:   claude-code | codex | cursor
#   status:  copied | none | unsupported
#   count:   <n>            (only when status=copied)
#   path:    <dest path>    (only when status=copied)
# After all agents, one summary line:
#   total_bytes: <n>
#
# Exit codes:
#   0 — ran to completion (regardless of whether any transcripts were found)
#   2 — bad arguments
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: copy-transcripts.sh PROJECT_DIR DEST_DIR" >&2
  exit 2
fi

PROJECT_DIR=$1
DEST_DIR=$2

mkdir -p "$DEST_DIR"

# ── Claude Code ──────────────────────────────────────────────────────────────
encoded=$(printf '%s' "$PROJECT_DIR" | sed 's|/|-|g')
claude_src="$HOME/.claude/projects/$encoded"
if [ -d "$claude_src" ]; then
  out="$DEST_DIR/claude-code"
  mkdir -p "$out"
  count=0
  for f in "$claude_src"/*.jsonl; do
    [ -f "$f" ] || continue
    cp "$f" "$out/"
    count=$((count + 1))
  done
  if [ "$count" -gt 0 ]; then
    printf 'agent: claude-code\nstatus: copied\ncount: %d\npath: %s\n\n' "$count" "$out"
  else
    rmdir "$out" 2>/dev/null || true
    printf 'agent: claude-code\nstatus: none\n\n'
  fi
else
  printf 'agent: claude-code\nstatus: none\n\n'
fi

# ── Codex CLI ────────────────────────────────────────────────────────────────
# Rollouts are organized by date, not cwd. Each rollout's first JSON record
# carries a `cwd` field — match on that.
codex_src="$HOME/.codex/sessions"
if [ -d "$codex_src" ]; then
  out="$DEST_DIR/codex"
  mkdir -p "$out"
  count=0
  while IFS= read -r -d '' f; do
    if command -v jq >/dev/null 2>&1; then
      rollout_cwd=$(head -n1 "$f" | jq -r '.cwd // .payload.cwd // empty' 2>/dev/null || true)
    else
      # Best-effort fallback: grep the literal cwd string in the first line.
      if head -n1 "$f" | grep -Fq "\"$PROJECT_DIR\""; then
        rollout_cwd=$PROJECT_DIR
      else
        rollout_cwd=""
      fi
    fi
    if [ "$rollout_cwd" = "$PROJECT_DIR" ]; then
      cp "$f" "$out/"
      count=$((count + 1))
    fi
  done < <(find "$codex_src" -name 'rollout-*.jsonl' -print0 2>/dev/null)
  if [ "$count" -gt 0 ]; then
    printf 'agent: codex\nstatus: copied\ncount: %d\npath: %s\n\n' "$count" "$out"
  else
    rmdir "$out" 2>/dev/null || true
    printf 'agent: codex\nstatus: none\n\n'
  fi
else
  printf 'agent: codex\nstatus: none\n\n'
fi

# ── Cursor ───────────────────────────────────────────────────────────────────
# Cursor's chat history lives in a per-workspace SQLite blob whose schema
# shifts across versions. Rather than parse it, we ask the user to use
# Cursor's built-in "Export Chat" (Cmd-Shift-P → "Cursor: Export Chat") and
# drop the resulting markdown files into <PROJECT_DIR>/.cursor-chat/ before
# running submit.
cursor_src="$PROJECT_DIR/.cursor-chat"
if [ -d "$cursor_src" ]; then
  out="$DEST_DIR/cursor"
  mkdir -p "$out"
  count=0
  while IFS= read -r -d '' f; do
    rel=${f#"$cursor_src"/}
    d="$out/$rel"
    mkdir -p "$(dirname "$d")"
    cp "$f" "$d"
    count=$((count + 1))
  done < <(find "$cursor_src" -type f -print0 2>/dev/null)
  if [ "$count" -gt 0 ]; then
    printf 'agent: cursor\nstatus: copied\ncount: %d\npath: %s\n\n' "$count" "$out"
  else
    rmdir "$out" 2>/dev/null || true
    printf 'agent: cursor\nstatus: empty\nreason: .cursor-chat exists but contains no files\n\n'
  fi
else
  printf 'agent: cursor\nstatus: none\nreason: no .cursor-chat directory in project (use Cursor'\''s Export Chat to populate it)\n\n'
fi

# ── Summary ──────────────────────────────────────────────────────────────────
total_bytes=$(find "$DEST_DIR" -type f -print0 2>/dev/null | xargs -0 wc -c 2>/dev/null | awk 'END{print $1+0}')
printf 'total_bytes: %s\n' "${total_bytes:-0}"
