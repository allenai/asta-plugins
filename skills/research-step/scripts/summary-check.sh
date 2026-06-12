#!/usr/bin/env bash
# summary-check.sh — check whether summary.md is consistent with beads.
#
# Consistency means: summary.md exists, has a `beads_snapshot` value in its
# YAML frontmatter, and that value equals a hash computed from the sorted IDs of
# currently-open (status != closed) issues. Adding or closing an issue invalidates
# the file; edits within an already-open or already-closed issue do not.
#
# Output (stdout, key: value lines):
#   status: fresh | missing | stale | no-tools
#   hash:   <current snapshot hash>   (omitted when status=no-tools)
#   reason: <details>                 (only when status=stale or status=missing)
# Diagnostics (human-readable) are also mirrored to stderr on non-fresh exits.
#
# Exit codes mirror status so scripted callers can branch on `$?`:
#   0 — fresh
#   1 — missing
#   2 — stale (includes "frontmatter has no beads_snapshot")
#   3 — no-tools (bd or jq missing)
set -euo pipefail

if ! command -v bd >/dev/null 2>&1; then
  echo "status: no-tools"
  echo "summary-check.sh: 'bd' CLI not found on PATH" >&2
  exit 3
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "status: no-tools"
  echo "summary-check.sh: 'jq' not found on PATH" >&2
  exit 3
fi

current=$(bd list --json --limit 0 \
  | jq -r '.[] | select(.status != "closed") | .id' \
  | sort \
  | shasum -a 256 \
  | awk '{print $1}')

if [[ ! -f summary.md ]]; then
  echo "status: missing"
  echo "hash: $current"
  echo "reason: summary.md does not exist"
  echo "summary-check.sh: summary.md is missing" >&2
  exit 1
fi

# Extract beads_snapshot from the YAML frontmatter (between leading `---` and the next `---`).
file_snapshot=$(awk '
  /^---[[:space:]]*$/ { fm++; if (fm == 2) exit; next }
  fm == 1 && /^beads_snapshot:/ {
    sub(/^beads_snapshot:[[:space:]]*/, "")
    gsub(/[[:space:]]+$/, "")
    print
    exit
  }
' summary.md)

if [[ -z "$file_snapshot" ]]; then
  echo "status: stale"
  echo "hash: $current"
  echo "reason: summary.md has no beads_snapshot in frontmatter"
  echo "summary-check.sh: summary.md has no beads_snapshot in frontmatter" >&2
  exit 2
fi

if [[ "$file_snapshot" != "$current" ]]; then
  echo "status: stale"
  echo "hash: $current"
  echo "reason: file=$file_snapshot current=$current"
  echo "summary-check.sh: stale (file=$file_snapshot current=$current)" >&2
  exit 2
fi

echo "status: fresh"
echo "hash: $current"
