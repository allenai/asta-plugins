# Workflow: execute

Run one ready task end-to-end. Loads its schema, gathers its declared inputs, produces a structured output, validates it, and closes the issue. After closing, hands off to **plan** if the closed task type unlocks new graph structure; otherwise hands off to **update-summary**.

## Preconditions

- An epic root exists (`scripts/epic-root.sh` prints `status: found`).
- An open issue with a `task_type` exists, **or** the caller supplied a specific `open` task ID.

## Steps

1. **Pick a task.** If a task ID was supplied, use it. Else pick the **open issue that has a `task_type` and the smallest hierarchical id** — `bd list --json`, keep `status == open` with `metadata.research_step.task_type != null`, sort by id, take the first. Grouping issues (epics, no `task_type`) are never executed; `close-task.sh` closes them when their last child closes. Do not use `bd ready` — there are no dependency edges, so id order is the ordering signal.
2. **Claim it.** `bd update <id> --status=in_progress`.
3. **Load the schema.** Read the flow and task type with `bd show <id> --json | jq -r '.[0].metadata.research_step | .flow, .task_type'`. In `assets/schemas.yaml`: the task's output shape is `tasks.<task_type>`; find the step by its `task_type` inside `flows.<flow>` — it may be nested under a fan-out group (e.g. `flows.reproduction.replication.reproduction_design`) — and use its `mission` and `chain`.
4. **Gather inputs.** For every issue listed in this issue's `inputs` (`bd show <id> --json | jq '.[0].metadata.research_step.inputs'`), read its output with `bd show <input-id> --json | jq '.[0].metadata.research_step.output_json'`. Also load `mission.md` and any files referenced from input outputs via `_path` fields (e.g., `summary_path` from `reproduction_synthesis`). **This is the only context to use** — do not pull in unrelated repo state.
5. **Do the work.** Follow the step's `mission` and run its `chain` (the asta commands). Produce two things:
   - **`output_json`** — a JSON object holding exactly the schema's output keys for this task (`tasks.<task_type>.output`) plus `artifacts`, and nothing else; derived or operational values (a verdict, an execution id, artifact paths) go in `artifacts`, not the typed fields. Keep it slim: beads stores metadata inline and rejects large blobs (~64KB+), so put heavy data (raw agent JSON, datasets, full extractions) under `.asta/<agent>/<slug>/` and reference it by repo-root-relative path. `<agent>` is the asta command group (`literature`, `generate-theories`, `autodiscovery`, `analyze-data`); `<slug>` is `YYYY-MM-DD-<short-query-slug>`. Preserve evidence uuids that tie a finding back to its paper. For schema fields ending in `_path`, write the file first and put the path in the JSON.
   - **`output_markdown`** — a concise write-up of the result, one `## <key>` section per output key. Reference artifacts, papers (canonical Semantic Scholar `/paper/<sha>` URLs), and deciding tasks by link where it helps a reader. This is guidance, not a gate — the scripts do not assert style. Keep it a digest; heavy data stays in the artifact files.
6. **Finish with `close-task.sh`.** Write the two files — `output.json` (the `output_json` object) and `output.md` (the `output_markdown`) — then run `scripts/close-task.sh <id> <output.json> <output.md>`. It publishes both into the issue metadata, validates `output_json` structurally against the schema (keys must equal `tasks.<task_type>.output` plus `artifacts`; no style checks), closes the issue, confirms it closed, and closes any ancestor group whose last child just closed. A non-zero exit leaves the issue `in_progress` — fix and re-run. The `description` is untouched; it stays the brief one-liner set at creation.
7. **Hand off.** If the flow has steps after this one, hand off to **plan** (source = this issue) to create them; plan chains to **update-summary**. If this was the flow's final synthesis, hand off to **update-summary** directly.

## Notes on output

The structured result is `metadata.research_step.output_json`; the narrative is `metadata.research_step.output_markdown`. The issue **`description`** is the brief one-liner set at creation by `create-task.sh` and is not overwritten. Heavy artifacts live under `.asta/<agent>/<slug>/` where `<slug>` is `YYYY-MM-DD-<short-query-slug>`, referenced by repo-root-relative path (`.asta/<agent>/<slug>/<file>`, repo files like the auto-ds inputs as `inputs/<path>`).

Schema fields ending in `_path` are repo-root-relative paths — write the file before putting the path in `output_json`:

- `report_path` (from every synthesis report — `reproduction_synthesis`, `theory_synthesis`, `verification_synthesis`, `gap_synthesis`, `final_synthesis`) → the report's `.md` deliverable. The master `final_synthesis` report is typically `report.md` at the repo root; the per-sub-flow reports go under `.asta/<agent>/<slug>/` or alongside it (e.g. `reproduction_report.md`, `theory_report.md`, `verification_report.md`, `data_gaps_report.md`).

If the executor crashes between writing a file and closing the issue, the file is harmless orphan data — re-running `execute` overwrites it.

## Out of scope for this workflow

- Validating output *quality* (correctness, novelty, soundness). Schema validation is structural only.
- Caching or skipping work. There is no `repro`. Closed issues stay closed; if a premise changed, re-open or re-create the affected task by hand.
- Updating `summary.md`. That belongs to `update-summary` and runs immediately after this workflow (directly or via `plan`).
- Designing the next set of tasks. That belongs to `plan`.
