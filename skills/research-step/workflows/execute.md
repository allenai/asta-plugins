# Workflow: execute

Propose ready tasks for researcher approval, then run the confirmed task end-to-end. Loads its schema, gathers its declared inputs, produces a structured output, validates it, and closes the issue. After closing, hands off to **reflect**.

## Preconditions

- An epic root exists (`scripts/epic-root.sh` prints `status: found`).
- `bd ready --json` is non-empty, **or** the caller supplied a specific task ID that is currently `open` and unblocked.

## Steps

1. **Propose candidates** (skip if a specific task ID was supplied). Read
   `summary.md` for current session state. Run `bd ready --json`; if empty,
   report "no ready tasks — graph is blocked or complete" and stop.

   Propose **2–3 candidates** from the ready list. For each, state:
   - Task ID and `task_type`
   - Which exploratory dimension(s) from `mission.md` it addresses, and at what priority
   - The specific question or gap it targets
   - Any risks (scope creep, rabbit holes, blocked dependencies)
 
   End with: "Which would you like to run? Reply with the number, suggest a
   modification, or say 'go' to proceed with option 1."

   **Stop and wait for researcher input before continuing.**


2. **Claim the chosen task.** Use the task ID supplied by the caller
   (step 0) or selected by the researcher in step 1. Run
   `bd update <id> --status=in_progress`. Hypothesis tasks are normally
   auto-resolved at creation by **plan**, so they should not appear as
   ready. If the researcher picks one, it means the gap text was too
   thin for plan to fill the output without inventing content — flag
   this and ask whether to refine the source `literature_review` first.

3. **Load the schema.** Read `metadata.research_step.task_type` from the issue. Open `assets/schemas.yaml` and find the matching entry under `task_types`.
4. **Gather inputs.** Read the `metadata.research_step.output` of every issue listed in this issue's `inputs`. Also load `mission.md` and any files referenced from input outputs via `_path` fields (e.g., `summary_path` from a `literature_review`). **This is the only context to use** — do not pull in unrelated repo state.
5. **Do the work.** Produce a JSON object matching the schema. For schema fields ending in `_path`, write the file to disk first and put the relative path in the JSON.
6. **Validate structurally.** Run `scripts/validate-output.sh <task_type> <metadata-json-file>`. It checks the envelope (`research_step.task_type`, `inputs`, `output_schema_version`, `output`) and every required `output.<key>` for the task_type, plus type spot-checks for the high-leverage cases (e.g., `analysis.verdict` enum, `analysis.confidence` range). Exit 0 ⇒ valid. Any non-zero exit ⇒ fail loudly and **leave the issue `in_progress`** for retry. Do not close.
7. **Persist the output.** Materialize the metadata JSON via `scripts/write-meta.sh` (reads JSON from stdin, prints a temp file path), then `bd update <id> --metadata @<path>`. Preserve the existing `task_type`, `inputs`, and `output_schema_version`.
8. **Close.** `bd close <id>`.
9. **Hand off to reflect.** Pass this task's ID and `task_type` to **reflect**. It decides whether to run the reflection, then chains to **plan** or **update-summary**. Either path ends with `summary.md` rebuilt.

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
