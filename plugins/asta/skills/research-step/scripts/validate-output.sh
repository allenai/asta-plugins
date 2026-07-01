#!/usr/bin/env bash
# validate-output.sh <issue-id> — structural check of a task's stored output_json.
# Reads the issue from beads and deep-validates metadata.research_step.output_json
# against the compiled JSON Schema (assets/compiled/<task_type>.schema.json,
# regenerated from schemas.yaml by scripts/compile-schemas.py at build time):
# top-level keys closed, declared nested fields required, extra nested fields
# permitted (payloads nest verbatim). No style or quality linting.
# Exit: 0 ok · 1 usage · 2 bad issue/metadata · 3 unknown task
#       · 4 schema violation
#       · 5 schema unreadable (PyYAML/jsonschema missing or compiled schema
#         absent — run the init workflow, or update the plugin)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ $# -eq 1 ]] || { echo "usage: validate-output.sh <issue-id>" >&2; exit 1; }
id="$1"

rs="$(bd show "$id" --json 2>/dev/null | jq -c '.[0].metadata.research_step // empty')"
[[ -n "$rs" ]] || { echo "validate-output: $id has no metadata.research_step" >&2; exit 2; }
task_type="$(jq -r '.task_type // empty' <<<"$rs")"
[[ -n "$task_type" ]] || { echo "validate-output: $id has no task_type" >&2; exit 2; }

# Exits 3 (unknown task_type) or 5 (schema unreadable) with its own message.
"$here/task-output-keys.sh" "$task_type" >/dev/null

got="$(jq -c '.output_json // empty' <<<"$rs")"
[[ -n "$got" && "$got" != "null" ]] || { echo "validate-output: $id has no output_json" >&2; exit 4; }

schema="$here/../assets/compiled/${task_type}.schema.json"
[[ -r "$schema" ]] || {
  echo "validate-output: compiled schema missing for '$task_type' ($schema) — update the plugin (it is regenerated at build time)" >&2
  exit 5
}
OUTPUT_JSON="$got" python3 - "$schema" "$task_type" <<'PY'
import json
import os
import sys

try:
    import jsonschema
except ImportError:
    print("validate-output: python3 cannot import jsonschema - run the init workflow", file=sys.stderr)
    sys.exit(5)

with open(sys.argv[1]) as f:
    schema = json.load(f)
data = json.loads(os.environ["OUTPUT_JSON"])

validator = jsonschema.Draft202012Validator(schema)
errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
if errors:
    for e in errors[:5]:
        path = ".".join(str(p) for p in e.absolute_path)
        where = f"output_json.{path}" if path else "output_json"
        hint = ""
        if e.validator == "additionalProperties" and not path:
            hint = " - byproducts go in artifacts"
        print(f"validate-output: {where}: {e.message}{hint}", file=sys.stderr)
    if len(errors) > 5:
        print(f"validate-output: ... and {len(errors) - 5} more schema violation(s)", file=sys.stderr)
    print(f"validate-output: output_json does not satisfy the '{sys.argv[2]}' schema", file=sys.stderr)
    sys.exit(4)
PY

echo "ok"
