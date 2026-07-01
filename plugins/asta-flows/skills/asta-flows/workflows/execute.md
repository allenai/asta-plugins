# Workflow: execute

Run one ready task end-to-end. Loads its schema, gathers its declared inputs, produces a structured output, validates it, and closes the issue. After closing, hands off to **plan** if the closed task type unlocks new graph structure; otherwise hands off to **update-summary**.

## Preconditions

- An epic root exists (`scripts/epic-root.sh` prints `status: found`).
- `bd ready --json` is non-empty, **or** the caller supplied a specific task ID that is currently `open` and unblocked.

## Steps

1. **Pick a task.** If a task ID was supplied, use it. Else `bd ready --json` and pick the oldest issue (tiebreak by `bd-id` ascending). Hypothesis tasks are normally auto-resolved at creation by **plan**, so they should not appear here. If one does, it means the gap text was too thin for plan to fill the output without inventing content — flag this to the user and ask whether to refine the source `literature_review` first.
2. **Claim it.** `bd update <id> --status=in_progress`.
3. **Load the schema.** Read the task type with `bd show <id> --json | jq -r '.[0].metadata.research_step.task_type'`. Open `assets/schemas.yaml` and find the matching entry under `task_types`.
4. **Gather inputs.** For every issue listed in this issue's `inputs` (`bd show <id> --json | jq '.[0].metadata.research_step.inputs'`), read its output with `bd show <input-id> --json | jq '.[0].metadata.research_step.output'`. Also load `mission.md` and any files referenced from input outputs via `_path` fields (e.g., `summary_path` from a `literature_review`). **This is the only context to use** — do not pull in unrelated repo state.
5. **Do the work.** Produce a JSON object matching the schema. For schema fields ending in `_path`, write the file to disk first and put the relative path in the JSON.
6. **Validate structurally.** Run `scripts/validate-output.sh <task_type> <metadata-json-file>`. It checks the envelope (`research_step.task_type`, `inputs`, `output_schema_version`, `output`) and every required `output.<key>` for the task_type, plus type spot-checks for the high-leverage cases (e.g., `analysis.verdict` enum, `analysis.confidence` range). Exit 0 ⇒ valid. Any non-zero exit ⇒ fail loudly and **leave the issue `in_progress`** for retry. Do not close.
7. **Persist the output.** Materialize the metadata JSON via `scripts/write-meta.sh` (reads JSON from stdin, prints a temp file path), then `bd update <id> --metadata @<path>`. Preserve the existing `task_type`, `inputs`, and `output_schema_version`.
8. **Close.** `bd close <id>`.
9. **Hand off to plan or update-summary.** Some closed task types unlock new graph structure; others don't. Decide based on the closed task's `task_type`:

   | Closed task_type | Hand off to |
   |---|---|
   | `literature_review`, `hypothesis`, `analysis`, `synthesis` | **plan** (with this issue as the source). `plan` then chains to **update-summary**. Note: `hypothesis` only reaches this branch in the rare case it was left open at creation; the normal path is plan→auto-resolve. |
   | `scope`, `definitions`, `experiment_design`, `evidence_gathering` | **update-summary** directly. |

   Either path ends with `summary.md` rebuilt.

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
