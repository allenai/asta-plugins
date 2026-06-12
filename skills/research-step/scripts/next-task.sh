#!/usr/bin/env bash
# next-task.sh — the single definition of task ordering. Prints the open task
# issues (status == open, metadata.research_step.task_type set), sorted
# *numerically* by hierarchical id (wf.1.2 before wf.1.10 — a plain lexical
# sort would get this wrong past 9 siblings). Groups (no task_type) are never
# listed; there are no dependency edges, so this order is the ordering signal.
#
# Used by execute (pick the next task) and update-summary (render the queue),
# so the two never disagree about what runs next.
#
# Output (stdout, key: value lines):
#   next:  <bd-id> | none
#   queue: <space-separated bd-ids>   (omitted when empty)
# Exit: 0 (even when next: none) · 3 bd/jq missing
set -euo pipefail

command -v bd >/dev/null 2>&1 || { echo "next-task: 'bd' not found on PATH" >&2; exit 3; }
command -v jq >/dev/null 2>&1 || { echo "next-task: 'jq' not found on PATH" >&2; exit 3; }

ids="$(bd list --json --limit 0 | jq -r '
  [ .[]
    | select(.status == "open")
    | select(.metadata.research_step.task_type != null) ]
  | sort_by(.id | split(".") | map(tonumber? // .))
  | .[].id')"

if [[ -z "$ids" ]]; then
  echo "next: none"
  exit 0
fi

echo "next: $(head -n1 <<<"$ids")"
rest="$(tail -n +2 <<<"$ids" | tr '\n' ' ' | sed 's/ $//')"
[[ -n "$rest" ]] && echo "queue: $rest" || true
