#!/usr/bin/env bash
# close-task.sh <issue-id> <output-json> <output-markdown>
# Publish a task's output and finish it: write output_json + output_markdown into the issue
# metadata, validate output_json against the schema, close the issue, assert it closed, then
# close any ancestor group whose last child just closed.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ $# -eq 3 ]] || { echo "usage: close-task.sh <issue-id> <output-json> <output-markdown>" >&2; exit 1; }
id="$1"; oj="$2"; om="$3"
[[ -f "$oj" ]] || { echo "close-task: no output-json $oj" >&2; exit 1; }
[[ -f "$om" ]] || { echo "close-task: no output-markdown $om" >&2; exit 1; }
jq -e . "$oj" >/dev/null 2>&1 || { echo "close-task: $oj is not valid JSON" >&2; exit 1; }

# 1. publish: merge output_json + output_markdown into the existing research_step metadata
cur="$(bd show "$id" --json | jq -c '.[0].metadata')"
merged="$(jq -c --slurpfile oj "$oj" --rawfile om "$om" \
  '.research_step.output_json = $oj[0] | .research_step.output_markdown = $om' <<<"$cur")"
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
printf '%s' "$merged" > "$tmp"
bd update "$id" --metadata @"$tmp" >/dev/null

# 2. validate structurally (reads the issue back; no style lint)
bash "$here/validate-output.sh" "$id"

# 3. close and 4. assert closure
bd close "$id" >/dev/null
[[ "$(bd show "$id" --json | jq -r '.[0].status')" == "closed" ]] \
  || { echo "close-task: $id did not close" >&2; exit 2; }
echo "closed $id"

# 5. cascade: close each ancestor group whose direct children are all closed.
# The epic root is never closed here — "root open, no open tasks" is the
# session-complete state that epic-root.sh and the workflows rely on.
cur_id="$id"
while [[ "$cur_id" == *.* ]]; do
  parent="${cur_id%.*}"
  parent_json="$(bd show "$parent" --json 2>/dev/null)" || break
  [[ "$(jq -r '.[0].metadata.research_step.epic_root // false' <<<"$parent_json")" == "true" ]] && break
  open_kids="$(bd list --json --limit 0 | jq --arg p "$parent" '
    [ .[]
      | select(.id | startswith($p + "."))
      | select((.id[($p|length)+1:] | contains(".")) | not)
      | select(.status != "closed") ] | length')"
  [[ "$open_kids" -eq 0 ]] || break
  if bd close "$parent" >/dev/null 2>&1; then
    echo "closed group $parent"
  else
    echo "close-task: warning: could not close group $parent (task $id is closed; close the group manually)" >&2
    break
  fi
  cur_id="$parent"
done
