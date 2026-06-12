#!/usr/bin/env bash
# create-task.sh <parent-id> <task_type> <flow> <title> <brief-description> [input-id ...]
# Create a leaf task issue under <parent-id>: hierarchical id, a brief one-line description,
# and initialized research_step metadata. output_json / output_markdown stay null until
# execute publishes them via close-task.sh. Prints the new issue id.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
schemas="$here/../assets/schemas.yaml"

[[ $# -ge 5 ]] || { echo "usage: create-task.sh <parent-id> <task_type> <flow> <title> <brief-desc> [input-id ...]" >&2; exit 1; }
parent="$1"; task_type="$2"; flow="$3"; title="$4"; desc="$5"; shift 5

python3 - "$schemas" "$task_type" <<'PY' || { echo "create-task: unknown task_type '$2' (not in schemas.yaml)" >&2; exit 3; }
import yaml, sys
d = yaml.safe_load(open(sys.argv[1]))
sys.exit(0 if sys.argv[2] in d["tasks"] else 3)
PY

[[ -n "$desc" ]]            || { echo "create-task: a brief description is required" >&2; exit 4; }
[[ "$desc" != *$'\n'* ]]    || { echo "create-task: description must be one line" >&2; exit 4; }
[[ "${#desc}" -le 200 ]]    || { echo "create-task: description too long (${#desc} chars > 200) — keep it brief" >&2; exit 4; }

if [[ $# -eq 0 ]]; then inputs_json="[]"; else inputs_json="$(printf '%s\n' "$@" | jq -R . | jq -cs .)"; fi
meta="$(jq -nc --arg f "$flow" --arg tt "$task_type" --argjson inp "$inputs_json" \
  '{research_step: {flow: $f, task_type: $tt, inputs: $inp, output_schema_version: 1, output_json: null, output_markdown: null}}')"
tmp="$(mktemp)"; printf '%s' "$meta" > "$tmp"
bd create "$title" --parent "$parent" -d "$desc" --metadata @"$tmp" --silent
