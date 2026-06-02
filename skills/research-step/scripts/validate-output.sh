#!/usr/bin/env bash
# validate-output.sh — structural validation of a research_step output JSON.
#
# Usage: validate-output.sh <task_type> <metadata-json-file> [task-dir]
#
# Verifies that the JSON file:
#   1. parses
#   2. carries the metadata envelope
#      ({research_step: {task_type, inputs, output_schema_version, output}})
#   3. has every required `output.<key>` for the given <task_type> per
#      assets/schemas.yaml (schema_version: 1)
# If [task-dir] (e.g. .asta/tasks/<id>) is given, also runs document-quality
# checks on its output.md.
#
# Exit codes:
#   0  — valid
#   2  — JSON parse error
#   3  — unknown task_type
#   4  — missing required field
#   5  — task_type mismatch with envelope
#   6  — required output.md missing (only when [task-dir] supplied)
#   7  — output.md empty or a stub (only when [task-dir] supplied)
#   8  — output.md has no markdown links (only when [task-dir] supplied)
#   9  — a named entity is unlinked (only when [task-dir] supplied)
#   10-15 — report node only (when artifacts/report.tex exists): report.pdf missing (10),
#           no title-page workflow diagram (11), no TOC (12), <8 sections (13),
#           <3 embedded figures (14), a required section is missing (15)
#
# Structural checks only — required fields, working links, and the report's basic pieces.
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: validate-output.sh <task_type> <metadata-json-file> [task-dir]" >&2
  exit 1
fi

task_type="$1"
file="$2"
task_dir="${3:-}"

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
  auto_discovery)     required="runid status experiments_path surprising_nodes" ;;
  analysis)           required="verdict confidence reasoning caveats" ;;
  synthesis)          required="answer supporting_hypotheses refuted_hypotheses open_questions report_path" ;;
  *)
    echo "validate-output: unknown task_type '$task_type'" >&2
    echo "validate-output: expected one of scope|definitions|literature_review|hypothesis|experiment_design|evidence_gathering|auto_discovery|analysis|synthesis" >&2
    exit 3
    ;;
esac

# The envelope must carry the matching task_type so we don't validate scope JSON
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

# Envelope shape.
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

# output.md document-quality gate. Every task must produce a human-readable
# output.md (skill "Task outputs" table) that links the entities it names.
if [[ -n "$task_dir" ]]; then
  md="$task_dir/output.md"
  if [[ ! -f "$md" ]]; then
    echo "validate-output: required output.md not found at '$md'" >&2
    exit 6
  fi
  if [[ "$(grep -cve '^[[:space:]]*$' "$md" || true)" -lt 3 ]]; then
    echo "validate-output: output.md is empty or a stub (<3 non-blank lines)" >&2
    exit 7
  fi
  if ! grep -qE '\[[^]]+\]\([^)]+\)' "$md"; then
    echo "validate-output: output.md has no markdown links" >&2
    exit 8
  fi
  # Strip links, then flag any named entity still bare in output.md / report.tex.
  unlinked=$(for f in "$md" "$task_dir/artifacts/report.tex" "$task_dir/report.tex"; do
    [[ -f "$f" ]] && perl -ne '
      if (/^\s*```/) { $fence = !$fence; next } next if $fence;
      s/!?\[[^\]]*\]\([^)]*\)//g; s/\\(?:href|ref|autoref|includegraphics|label|cite[a-z]*)(?:\[[^\]]*\])?\{[^}]*\}(\{[^}]*\})?//g;
      while (/(node_\d+_\d+|\bL\d+\b|theory-\d+-\d+|\([A-Z][a-z]+(?: et al\.?)?,? \d{4}\)|[\w.\/-]+\.(?:csv|jsonl|json|png|tex|pdf|parquet|xlsx))/g) { print "$ARGV:$.: $1\n" }
    ' "$f"
  done) || true
  if [[ -n "$unlinked" ]]; then
    echo "$unlinked" >&2
    echo "validate-output: named entities above are unlinked" >&2
    exit 9
  fi

  # The report's basics. Only the report node makes report.tex; when it exists,
  # check it has what report_example.tex has. Each failure points back to it.
  rpt="$task_dir/artifacts/report.tex"
  if [[ -f "$rpt" ]]; then
    ref="templates/examples/report_example.tex"
    rfail() {
      echo "report-gate: $1" >&2
      echo "  -> this is the minimum, not the goal. Re-read $ref in full and match" >&2
      echo "     its depth and citation density before retrying." >&2
      exit "$2"
    }
    [[ -f "$task_dir/artifacts/report.pdf" ]] || rfail "report.pdf missing — compile report.tex" 10
    grep -q '\\begin{tikzpicture}\|\\includegraphics' \
      <(sed -n '/begin{titlepage}/,/end{titlepage}/p' "$rpt") \
      || rfail "no title-page workflow diagram (see the TikZ flowchart in $ref)" 11
    grep -q '\\tableofcontents' "$rpt"                  || rfail "no \\tableofcontents" 12
    [[ "$(grep -c '\\section{' "$rpt")" -ge 8 ]]        || rfail "<8 sections — likely a skimmed, thin report" 13
    [[ "$(grep -c '\\includegraphics' "$rpt")" -ge 3 ]] || rfail "<3 embedded run figures" 14
    for s in Mission Abstract Methods Results Conclusion Catalogue Datasets References; do
      grep -qi "section{[^}]*$s" "$rpt" || rfail "missing section '$s' (present in $ref)" 15
    done
  fi
fi

echo "ok"
