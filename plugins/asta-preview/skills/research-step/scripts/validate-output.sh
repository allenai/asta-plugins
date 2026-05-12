#!/usr/bin/env bash
# validate-output.sh — structural validation of a research_step output JSON.
#
# Usage: validate-output.sh <task_type> <metadata-json-file>
#
# Verifies that the JSON file:
#   1. parses
#   2. carries the canonical metadata envelope
#      ({research_step: {task_type, inputs, output_schema_version, output}})
#   3. has every required `output.<key>` for the given <task_type> per
#      assets/schemas.yaml (schema_version: 1)
#
# Exit codes:
#   0  — valid
#   2  — JSON parse error
#   3  — unknown task_type
#   4  — missing required field
#   5  — task_type mismatch with envelope
#
# This is structural validation only. Quality validation (sound prediction,
# sane confidence, valid citations) is out of scope per execute.md.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: validate-output.sh <task_type> <metadata-json-file>" >&2
  exit 1
fi

task_type="$1"
file="$2"

if ! jq -e . "$file" > /dev/null 2>&1; then
  echo "validate-output: $file is not valid JSON" >&2
  exit 2
fi

# Required output fields, mirroring assets/schemas.yaml (schema_version: 1).
case "$task_type" in
  scope)              required="question boundaries success_criteria" ;;
  definitions)        required="terms" ;;
  literature_review)  required="summary_path key_findings gaps citations" ;;
  hypothesis)         required="statement rationale falsifiable_prediction expected_evidence" ;;
  experiment_design)  required="method procedure variables artifacts_expected" ;;
  evidence_gathering) required="artifacts log_path deviations" ;;
  analysis)           required="verdict confidence reasoning caveats" ;;
  synthesis)          required="answer supporting_hypotheses refuted_hypotheses open_questions report_path" ;;
  *)
    echo "validate-output: unknown task_type '$task_type'" >&2
    echo "validate-output: expected one of scope|definitions|literature_review|hypothesis|experiment_design|evidence_gathering|analysis|synthesis" >&2
    exit 3
    ;;
esac

# Envelope must carry the matching task_type so we don't validate scope JSON
# against an analysis schema by accident.
envelope_type=$(jq -r '.research_step.task_type // empty' "$file")
if [[ -z "$envelope_type" ]]; then
  echo "validate-output: $file missing .research_step.task_type" >&2
  exit 5
fi
if [[ "$envelope_type" != "$task_type" ]]; then
  echo "validate-output: envelope task_type='$envelope_type' but expected '$task_type'" >&2
  exit 5
fi

# Envelope shape sanity.
for key in inputs output_schema_version output; do
  if ! jq -e ".research_step | has(\"$key\")" "$file" >/dev/null; then
    echo "validate-output: $file missing .research_step.$key" >&2
    exit 5
  fi
done

# Required output fields.
for key in $required; do
  if ! jq -e ".research_step.output | has(\"$key\")" "$file" >/dev/null; then
    echo "validate-output: missing required field 'output.$key' for task_type '$task_type'" >&2
    exit 4
  fi
done

# Type spot-checks for the high-leverage cases. Not exhaustive — just the
# fields where a wrong type at this layer would silently break update-summary rendering
# or downstream tasks.
case "$task_type" in
  literature_review)
    jq -e '.research_step.output.key_findings | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: output.key_findings must be an array" >&2; exit 4; }
    jq -e '.research_step.output.gaps | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: output.gaps must be an array" >&2; exit 4; }
    jq -e '.research_step.output.citations | type == "array"' "$file" >/dev/null \
      || { echo "validate-output: output.citations must be an array" >&2; exit 4; }
    ;;
  analysis)
    jq -e '.research_step.output.verdict | IN("supported", "refuted", "inconclusive")' "$file" >/dev/null \
      || { echo "validate-output: output.verdict must be one of supported|refuted|inconclusive" >&2; exit 4; }
    jq -e '.research_step.output.confidence | type == "number" and . >= 0 and . <= 1' "$file" >/dev/null \
      || { echo "validate-output: output.confidence must be a number in [0, 1]" >&2; exit 4; }
    ;;
esac

echo "ok"
