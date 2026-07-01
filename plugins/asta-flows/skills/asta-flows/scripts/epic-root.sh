#!/usr/bin/env bash
# epic-root.sh — emit the bd ID of the research session's epic root.
#
# The epic root is any issue whose metadata.research_step.epic_root == true.
# A well-formed research session has exactly one.
#
# Used by update-summary, execute, plan, and brainstorm to locate (or check the
# existence of) the session's epic without each workflow re-implementing the jq filter.
#
# Output (stdout, key: value lines):
#   status: found | none | multiple | no-tools
#   id:     <bd-id>                  (only when status=found)
#   ids:    <space-separated bd-ids> (only when status=multiple)
# Diagnostics on non-found cases are also mirrored to stderr.
#
# Exit codes mirror status so scripted callers can branch on `$?`:
#   0 — found       (exactly one epic root)
#   1 — none        (no epic root yet — caller decides whether to bootstrap)
#   2 — multiple    (graph is malformed)
#   3 — no-tools    (bd or jq missing)
#
# To capture just the ID in shell:  epic_id=$(scripts/epic-root.sh | sed -n 's/^id: //p')
set -euo pipefail

if ! command -v bd >/dev/null 2>&1; then
  echo "status: no-tools"
  echo "epic-root.sh: 'bd' CLI not found on PATH" >&2
  exit 3
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "status: no-tools"
  echo "epic-root.sh: 'jq' not found on PATH" >&2
  exit 3
fi

ids=$(bd list --json | jq -r '.[] | select(.metadata.research_step.epic_root == true) | .id')
count=$(printf '%s' "$ids" | grep -c . || true)

case "$count" in
  0) echo "status: none"
     exit 1 ;;
  1) echo "status: found"
     printf 'id: %s\n' "$ids" ;;
  *) joined=$(printf '%s' "$ids" | tr '\n' ' ' | sed 's/ $//')
     echo "status: multiple"
     printf 'ids: %s\n' "$joined"
     echo "epic-root.sh: multiple epic roots found: $joined" >&2
     exit 2 ;;
esac
