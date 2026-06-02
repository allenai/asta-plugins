# Workflow: execute

Run one ready task end-to-end. Loads its schema, gathers its inputs, produces the output, validates it, and closes the issue. After closing, hands off to **plan**, which creates whatever comes next and then chains to **update-summary**.

## Preconditions

- An epic root exists (`scripts/epic-root.sh` prints `status: found`).
- `bd ready --json` is non-empty, **or** the caller supplied a specific task ID that is currently `open` and unblocked.

## Steps

1. **Pick a task.** If a task ID was supplied, use it. Else `bd ready --json` and pick the oldest issue (tiebreak by `bd-id` ascending). A hypothesis that just restates a gap or finding is auto-resolved by **plan** at creation, so it won't appear here — if one does, the source was too thin for plan to fill without inventing content; flag it to the user. (Hypothesis-typed tasks that run a skill, like the theorizer and novelty scoring, do execute here.)
2. **Claim it.** `bd update <id> --status=in_progress`.
3. **Load the schema.** Read the task type with `bd show <id> --json | jq -r '.[0].metadata.research_step.task_type'`. Open `assets/schemas.yaml` and find the matching entry under `task_types`.
4. **Gather inputs.** For every issue listed in this issue's `inputs` (`bd show <id> --json | jq '.[0].metadata.research_step.inputs'`), read its output with `bd show <input-id> --json | jq '.[0].metadata.research_step.output'`. Also load `mission.md` and any files referenced from input outputs via `_path` fields (e.g., `summary_path` from a `literature_review`). **This is the only context to use** — do not pull in unrelated repo state.
5. **Do the work.** Produce all three task outputs under `.asta/tasks/<id>/` — see the skill's "Task outputs" table for their roles. **All three are mandatory:** `output.json` (matches the schema), `output.md` (the readable result, with links per the template's writing rules), and `artifacts/` (every other file produced). For schema fields ending in `_path`, write the file first and put the relative path in the JSON.

   **If the task delegates to a remote A2A agent** (DataVoyager via `asta analyze-data`, the theorizer via `asta-preview:generate-theories`, the AutoExperimentDesigner via `asta auto-exp-designer`), the output must come from that agent's terminal response. Submit, poll to a terminal state, and wait for the completion notification before validating and closing — **the task is not done while the agent is still running.** Do not fabricate the agent's output, do not port it from a sibling run, and do not move on to the next ready task until this one's agent has returned.
6. **Validate.** Run `scripts/validate-output.sh <task_type> <metadata-json-file> .asta/tasks/<id>` — **always pass the task dir** so the `output.md` is gated: present (exit 6), non-empty (7), has links (8), no unlinked named entity (9). It also checks the wrapper and every required `output.<key>` for the task_type, plus type spot-checks (e.g., `analysis.verdict` enum, `analysis.confidence` range). When the task produced an `artifacts/report.tex` (the `report` node), it also checks the report has the basics (exits 10–15: PDF, title-page diagram, TOC, ≥8 sections, ≥3 figures, required sections). Exit 0 ⇒ valid. Any non-zero exit ⇒ fail loudly and **leave the issue `in_progress`** for retry. Do not close.
7. **Persist the output.** Write the metadata JSON via `scripts/write-meta.sh` (reads JSON from stdin, prints a temp file path), then `bd update <id> --metadata @<path>`. Preserve the existing `task_type`, `inputs`, and `output_schema_version`.
8. **Close.** `bd close <id>`.
9. **Hand off to plan.** Pass the closed task to **plan**; it creates whatever the template puts next (or no-ops if nothing new is ready), then chains to **update-summary**. Either way `summary.md` ends up rebuilt.

## Notes on output files

Schema fields ending in `_path` are relative paths. Conventions:

- `summary_path` (from `literature_review`) → `background_knowledge.txt` by convention, but any path works.
- `log_path` (from `evidence_gathering`) → typically under `logs/`.
- `report_path` (from `synthesis`) → typically `report.md`.

Write the file before setting the output JSON. If the executor crashes between writing the file and closing the issue, the file is harmless orphan data — re-running `execute` on the same issue will overwrite it.

## Out of scope for this workflow

- Validating output *quality* (correctness, novelty, soundness). Schema validation is structural only.
- Caching or skipping work. There is no `repro`. Closed issues stay closed; if a premise changed, re-open or re-create the affected task by hand.
- Updating `summary.md`. That belongs to `update-summary` and runs immediately after this workflow (directly or via `plan`).
- Designing the next set of tasks. That belongs to `plan`.
