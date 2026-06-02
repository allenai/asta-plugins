#!/usr/bin/env bash
# validate-output.sh — structural validation of a research_step output JSON.
#
# Usage: validate-output.sh <task_type> <metadata-json-file>
#
# Verifies that the JSON file:
#   1. parses
#   2. carries the canonical metadata envelope
#      ({research_step: {task_type, inputs, work_dir, output}})
#   3. has every required `output.<key>` for the given <task_type> per
#      assets/schemas.yaml (schema_version: 3)
#
# Exit codes:
#   0  — valid
#   2  — JSON parse error
#   3  — unknown task_type
#   4  — missing required field
#   5  — task_type mismatch with envelope
#   6  — bad work_dir format
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

# Required output fields, mirroring assets/schemas.yaml (schema_version: 3).
# Only structured-answer fields — paths and artifact lists are gone.
case "$task_type" in
  scope)                       required="question boundaries success_criteria" ;;
  definitions)                 required="terms" ;;
  literature_review)           required="key_findings gaps citations" ;;
  hypothesis)                  required="statement rationale falsifiable_prediction expected_evidence" ;;
  experiment_design)           required="method procedure variables artifacts_expected" ;;
  evidence_gathering)          required="deviations" ;;
  analysis)                    required="verdict confidence reasoning caveats" ;;
  synthesis)                   required="answer supporting_hypotheses refuted_hypotheses open_questions" ;;
  autods_run)                  required="run_id mode dataset_summary hypotheses surprising_count" ;;
  autods_literature_synthesis) required="themes surviving_findings contradicted_findings headline" ;;
  data_reproduction)           required="candidate_datasets findings deviations" ;;
  theorize)                    required="theory_query theories fallback_used" ;;
  *)
    echo "validate-output: unknown task_type '$task_type'" >&2
    echo "validate-output: expected one of scope|definitions|literature_review|hypothesis|experiment_design|evidence_gathering|analysis|synthesis|autods_run|autods_literature_synthesis|data_reproduction|theorize" >&2
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

# Envelope shape sanity. work_dir is the new mandatory pointer to this task's files.
for key in inputs work_dir output; do
  if ! jq -e ".research_step | has(\"$key\")" "$file" >/dev/null; then
    echo "validate-output: $file missing .research_step.$key" >&2
    exit 5
  fi
done

# work_dir format check: must be a run-root-relative path that starts with
# `.asta/<task_type>/` and ends with `/`. Catches drift from the convention.
work_dir=$(jq -r '.research_step.work_dir // empty' "$file")
if [[ -z "$work_dir" ]]; then
  echo "validate-output: .research_step.work_dir is empty" >&2; exit 6
fi
expected_prefix=".asta/${task_type}/"
case "$work_dir" in
  "$expected_prefix"*) : ;;
  *) echo "validate-output: work_dir '$work_dir' should start with '$expected_prefix'" >&2; exit 6 ;;
esac
case "$work_dir" in
  */) : ;;
  *) echo "validate-output: work_dir '$work_dir' must end with '/'" >&2; exit 6 ;;
esac
case "$work_dir" in
  /*|*..*) echo "validate-output: work_dir '$work_dir' must be run-root-relative (no leading '/', no '..')" >&2; exit 6 ;;
esac

# Required output fields.
for key in $required; do
  if ! jq -e ".research_step.output | has(\"$key\")" "$file" >/dev/null; then
    echo "validate-output: missing required field 'output.$key' for task_type '$task_type'" >&2
    exit 4
  fi
done

# Type spot-checks for the high-leverage cases. Not exhaustive — just the
# fields where a wrong type at this layer would silently break downstream tasks.
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
  autods_run)
    jq -e '.research_step.output.mode | IN("imported", "executed")' "$file" >/dev/null \
      || { echo "validate-output: output.mode must be one of imported|executed" >&2; exit 4; }
    ;;
  data_reproduction)
    if [[ $(jq '.research_step.output.findings | length' "$file") -gt 0 ]]; then
      jq -e '.research_step.output.findings[0].verdict | IN("reproduced","failed_to_reproduce","partial","inconclusive","unreachable")' "$file" >/dev/null \
        || { echo "validate-output: findings[].verdict must be one of reproduced|failed_to_reproduce|partial|inconclusive|unreachable" >&2; exit 4; }
    fi
    ;;
  theorize)
    jq -e '.research_step.output.fallback_used | type == "boolean"' "$file" >/dev/null \
      || { echo "validate-output: output.fallback_used must be boolean" >&2; exit 4; }
    if [[ $(jq '.research_step.output.theories | length' "$file") -gt 0 ]]; then
      jq -e '.research_step.output.theories[0].novelty_rollup | IN("genuinely-new","derivable-but-unstated","already-established")' "$file" >/dev/null \
        || { echo "validate-output: theories[].novelty_rollup must be one of genuinely-new|derivable-but-unstated|already-established" >&2; exit 4; }
    fi
    ;;
esac

echo "ok"
