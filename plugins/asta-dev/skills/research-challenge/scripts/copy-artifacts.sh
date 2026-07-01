#!/usr/bin/env bash
# copy-artifacts.sh — copy a list of project artifact paths into a destination
# directory, applying size limits and a fixed exclude list.
#
# Reads paths from stdin (one per line, relative to PROJECT_DIR). For each:
#   • skip if matched by the project's .gitignore (when PROJECT_DIR is a git repo)
#   • skip if name matches a hard-coded exclude (node_modules, .venv, etc.)
#   • for individual files, skip if size > ASTA_RC_MAX_FILE_MB (default 10)
#   • abort if cumulative copy size > ASTA_RC_MAX_TOTAL_MB (default 100)
#
# Usage:
#   echo -e "src/main.py\ndata/results.csv" | scripts/copy-artifacts.sh PROJECT_DIR DEST_DIR
#
# Output (stdout, key: value lines, one block per input path):
#   path:    <relative path>
#   status:  copied | skipped-missing | skipped-gitignore | skipped-excluded |
#            skipped-too-large | aborted-total-limit
#   reason:  <human-readable detail>            (only for skipped/aborted)
#   bytes:   <n>                                (only for copied)
# After all paths, one summary:
#   total_bytes: <n>
#
# Exit codes:
#   0 — ran to completion (some paths may have been skipped)
#   1 — aborted because total limit was exceeded
#   2 — bad arguments
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: copy-artifacts.sh PROJECT_DIR DEST_DIR  (paths on stdin)" >&2
  exit 2
fi

PROJECT_DIR=$1
DEST_DIR=$2

MAX_FILE_MB=${ASTA_RC_MAX_FILE_MB:-10}
MAX_TOTAL_MB=${ASTA_RC_MAX_TOTAL_MB:-100}
MAX_FILE_BYTES=$((MAX_FILE_MB * 1024 * 1024))
MAX_TOTAL_BYTES=$((MAX_TOTAL_MB * 1024 * 1024))

EXCLUDES='node_modules .venv venv __pycache__ .git .cache .mypy_cache .pytest_cache .tox .next dist build target'

mkdir -p "$DEST_DIR"

is_excluded_name() {
  local name=$1
  for ex in $EXCLUDES; do
    [ "$name" = "$ex" ] && return 0
  done
  return 1
}

# Returns 0 if path is ignored by the project's .gitignore.
is_gitignored() {
  local rel=$1
  [ -d "$PROJECT_DIR/.git" ] || return 1
  ( cd "$PROJECT_DIR" && git check-ignore -q -- "$rel" ) >/dev/null 2>&1
}

path_bytes() {
  local p=$1
  if [ -d "$p" ]; then
    find "$p" -type f -print0 2>/dev/null | xargs -0 wc -c 2>/dev/null | awk 'END{print $1+0}'
  elif [ -f "$p" ]; then
    wc -c < "$p" | awk '{print $1+0}'
  else
    echo 0
  fi
}

running_total=0

while IFS= read -r rel || [ -n "$rel" ]; do
  # Trim whitespace; skip blank lines.
  rel=${rel#"${rel%%[![:space:]]*}"}
  rel=${rel%"${rel##*[![:space:]]}"}
  [ -z "$rel" ] && continue

  abs="$PROJECT_DIR/$rel"

  if [ ! -e "$abs" ]; then
    printf 'path: %s\nstatus: skipped-missing\nreason: path does not exist\n\n' "$rel"
    continue
  fi

  base=$(basename "$rel")
  if is_excluded_name "$base"; then
    printf 'path: %s\nstatus: skipped-excluded\nreason: name in hard-coded exclude list\n\n' "$rel"
    continue
  fi

  if is_gitignored "$rel"; then
    printf 'path: %s\nstatus: skipped-gitignore\nreason: matched by project .gitignore\n\n' "$rel"
    continue
  fi

  size=$(path_bytes "$abs")
  if [ -f "$abs" ] && [ "$size" -gt "$MAX_FILE_BYTES" ]; then
    printf 'path: %s\nstatus: skipped-too-large\nreason: %d bytes exceeds per-file limit (%d MB)\n\n' \
      "$rel" "$size" "$MAX_FILE_MB"
    continue
  fi

  projected=$((running_total + size))
  if [ "$projected" -gt "$MAX_TOTAL_BYTES" ]; then
    printf 'path: %s\nstatus: aborted-total-limit\nreason: would push total past %d MB\n\n' \
      "$rel" "$MAX_TOTAL_MB"
    printf 'total_bytes: %s\n' "$running_total"
    exit 1
  fi

  dest="$DEST_DIR/$rel"
  mkdir -p "$(dirname "$dest")"
  if [ -d "$abs" ]; then
    # Recursive copy, but prune excludes and gitignored files mid-walk.
    ( cd "$PROJECT_DIR" && find "$rel" \
        \( $(printf '%s\n' $EXCLUDES | awk '{printf "-name %s -o ",$1}') -false \) -prune \
        -o -type f -print0 ) | while IFS= read -r -d '' file; do
      if is_gitignored "$file"; then
        continue
      fi
      d="$DEST_DIR/$file"
      mkdir -p "$(dirname "$d")"
      cp "$PROJECT_DIR/$file" "$d"
    done
  else
    cp "$abs" "$dest"
  fi

  running_total=$projected
  printf 'path: %s\nstatus: copied\nbytes: %s\n\n' "$rel" "$size"
done

printf 'total_bytes: %s\n' "$running_total"
