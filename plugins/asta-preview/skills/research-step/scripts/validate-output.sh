#!/usr/bin/env bash
# validate-output.sh <issue-id> — structural check of a task's stored output_json.
# Reads the issue from beads, compiles assets/schemas.yaml, and checks that
# metadata.research_step.output_json holds exactly tasks.<task_type>.output (incl. artifacts).
# No style or quality linting.
# Exit: 0 ok · 1 usage · 2 bad issue/metadata · 3 unknown task · 4 output_json mismatch
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
schemas="$here/../assets/schemas.yaml"

[[ $# -eq 1 ]] || { echo "usage: validate-output.sh <issue-id>" >&2; exit 1; }
id="$1"

rs="$(bd show "$id" --json 2>/dev/null | jq -c '.[0].metadata.research_step // empty')"
[[ -n "$rs" ]] || { echo "validate-output: $id has no metadata.research_step" >&2; exit 2; }
task_type="$(jq -r '.task_type // empty' <<<"$rs")"
[[ -n "$task_type" ]] || { echo "validate-output: $id has no task_type" >&2; exit 2; }

expected="$(python3 - "$schemas" "$task_type" <<'PY'
import yaml, sys
d = yaml.safe_load(open(sys.argv[1]))
t = d["tasks"].get(sys.argv[2])
if t is None: sys.exit(3)
print(" ".join(t["output"]))
PY
)" || { echo "validate-output: unknown task '$task_type' (not in schemas.yaml)" >&2; exit 3; }

got="$(jq -c '.output_json // empty' <<<"$rs")"
[[ -n "$got" && "$got" != "null" ]] || { echo "validate-output: $id has no output_json" >&2; exit 4; }

for k in $expected; do
  jq -e --arg k "$k" 'has($k)' <<<"$got" >/dev/null \
    || { echo "validate-output: output_json missing '$k' for '$task_type'" >&2; exit 4; }
done
while IFS= read -r k; do
  case " $expected " in *" $k "*) ;; *)
    echo "validate-output: output_json.$k is not in the '$task_type' schema — byproducts go in artifacts" >&2; exit 4 ;;
  esac
done < <(jq -r 'keys[]' <<<"$got")
jq -e '.artifacts | type == "array"' <<<"$got" >/dev/null \
  || { echo "validate-output: output_json.artifacts must be an array" >&2; exit 4; }

echo "ok"
