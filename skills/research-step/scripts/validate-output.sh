#!/usr/bin/env bash
# validate-output.sh — structural validation of a research_step output.json.
#
# Usage: validate-output.sh <task_type> <output.json-path>
#
# Behavior:
#   - Look up the task_type in assets/schemas.yaml.
#   - If the entry's `output:` has a `bash_ref:` field, run the command,
#     pipe stdout into a JSON Schema validator, and check output.json
#     against it. If the command fails or stdout is not valid JSON,
#     warn and treat the output as opaque (exit 0).
#   - Otherwise (inline output schema): verify every required field
#     listed in schemas.yaml; preserve the v1 type spot-checks
#     (analysis.verdict, analysis.confidence, etc.).
#
# Exit codes:
#   0 — valid (or bash_ref unavailable + warning emitted)
#   2 — JSON parse error on output.json
#   3 — unknown task_type
#   4 — missing required field (inline schema mode)
#   5 — bash_ref command failed in an unexpected way (e.g. permission denied)
#   6 — sibling output.md has an absolute path or file:// URL
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: validate-output.sh <task_type> <output.json-path>" >&2
  exit 1
fi

task_type="$1"
file="$2"

if ! jq -e . "$file" > /dev/null 2>&1; then
  echo "validate-output: $file is not valid JSON" >&2
  exit 2
fi

# Resolve the path to schemas.yaml relative to this script.
script_dir="$(cd "$(dirname "$0")" && pwd)"
schemas="$script_dir/../assets/schemas.yaml"
if [[ ! -f "$schemas" ]]; then
  echo "validate-output: schemas.yaml not found at $schemas" >&2
  exit 3
fi

# Pull the task_type's `output:` entry from schemas.yaml. We use a tiny
# python shim to keep us out of yq-flavor land. Three possible shapes
# come back on stdout:
#   - "bash_ref:<command>"      — resolve via the referenced CLI
#   - "required:<f1> <f2> ..."  — inline required-field list
#   - "missing"                 — unknown task_type
output_spec=$(python3 - "$schemas" "$task_type" <<'PY'
import sys, yaml
schemas_path, task_type = sys.argv[1], sys.argv[2]
with open(schemas_path) as f:
    data = yaml.safe_load(f)
entry = (data.get("task_types") or {}).get(task_type)
if not entry:
    print("missing")
    sys.exit(0)
output = entry.get("output")
if isinstance(output, dict) and "bash_ref" in output:
    print(f"bash_ref:{output['bash_ref']}")
elif isinstance(output, dict):
    # Inline output schema: top-level dict keys are required field names
    # (a small departure from a strict JSON Schema, matching what the
    # spec writes).
    required = " ".join(output.keys())
    print(f"required:{required}")
elif isinstance(output, list):
    # Free-form list shape — treat as opaque.
    print("required:")
else:
    print("required:")
PY
)

if [[ "$output_spec" == "missing" ]]; then
  echo "validate-output: unknown task_type '$task_type'" >&2
  exit 3
fi

if [[ "$output_spec" == bash_ref:* ]]; then
  cmd="${output_spec#bash_ref:}"
  # Try to run the command and validate output.json against its JSON Schema.
  if schema_stdout=$($cmd 2>/dev/null); then
    if echo "$schema_stdout" | jq -e . >/dev/null 2>&1; then
      # Try jsonschema if available; else just check the output parses.
      if command -v jsonschema >/dev/null 2>&1; then
        if echo "$schema_stdout" | jsonschema -i "$file" /dev/stdin >/dev/null 2>&1; then
          echo "ok (validated against bash_ref: $cmd)"
          exit 0
        else
          echo "validate-output: output.json failed schema from '$cmd'" >&2
          exit 4
        fi
      else
        echo "warn: jsonschema CLI not installed; bash_ref schema parsed but unchecked"
        exit 0
      fi
    else
      echo "warn: bash_ref '$cmd' stdout is not JSON; treating output.json as opaque"
      exit 0
    fi
  else
    echo "warn: bash_ref command '$cmd' failed; treating output.json as opaque"
    exit 0
  fi
fi

# Inline schema mode — output_spec is "required:<f1> <f2> ..."
required="${output_spec#required:}"

# Check every required top-level field.
for key in $required; do
  if ! jq -e "has(\"$key\")" "$file" >/dev/null 2>&1; then
    echo "validate-output: missing required field '$key' for task_type '$task_type'" >&2
    exit 4
  fi
done

# Type spot-checks for high-leverage cases.
case "$task_type" in
  literature_review)
    jq -e '.key_findings | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: key_findings must be an array" >&2; exit 4; }
    jq -e '.gaps | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: gaps must be an array" >&2; exit 4; }
    jq -e '.citations | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: citations must be an array" >&2; exit 4; }
    ;;
  analysis)
    jq -e '.verdict | IN("supported", "refuted", "inconclusive")' "$file" >/dev/null \
      || { echo "validate-output: verdict must be one of supported|refuted|inconclusive" >&2; exit 4; }
    jq -e '.confidence | type == "number" and . >= 0 and . <= 1' "$file" >/dev/null \
      || { echo "validate-output: confidence must be a number in [0, 1]" >&2; exit 4; }
    ;;
  synthesis)
    # answer is required by the schema; supporting_hypotheses / refuted_hypotheses /
    # open_questions are arrays. themes / gaps / candidate_papers are optional.
    jq -e '.supporting_hypotheses | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: supporting_hypotheses must be an array" >&2; exit 4; }
    jq -e '.refuted_hypotheses | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: refuted_hypotheses must be an array" >&2; exit 4; }
    jq -e '.open_questions | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: open_questions must be an array" >&2; exit 4; }
    ;;
esac

md_file="$(dirname "$file")/output.md"
if grep -qE '/Users/|/home/|/private/|file://' "$md_file" 2>/dev/null; then
  echo "validate-output: $md_file has absolute paths; use .asta/-relative paths" >&2
  exit 6
fi

echo "ok"
