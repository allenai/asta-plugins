# Workflow: execute

Run one ready task end-to-end. Materialize its `input.md` / `input.json` from the issue's metadata and upstream task outputs, invoke the agent to produce `output.md` / `output.json`, validate the result, persist pointers in beads, and close the issue. After closing, hand off to **plan** if the closed task type unlocks new structure; otherwise hand off to **update-summary**.

## Preconditions

- An epic root exists (`scripts/epic-root.sh` prints `status: found`).
- `bd ready --json` is non-empty, **or** the caller supplied a specific task ID that is currently `open` and unblocked.

## Steps

1. **Pick a task.** If a task ID was supplied, use it. Else `bd ready --json` and pick the oldest issue (tiebreak by `bd-id` ascending).

2. **Claim it.** `bd update <id> --status=in_progress`.

3. **Read the issue's metadata.**
   ```
   bd show <id> --json | jq '.[0].metadata.research_step'
   ```
   Extract `task_type`, `inputs[]`, `input_instructions`, `output_instructions`, `config`.

4. **Read the prepared inputs.** Plan has already written `.asta/tasks/<id>/input.md` (a short task brief with inline citations to upstream sources) and `.asta/tasks/<id>/input.json` (the structured upstream output fragments plus this task's config). Their paths are in `metadata.research_step.input_md` and `metadata.research_step.input_json`. The agent reads:
   - `input.md` for the human-readable brief.
   - `input.json` for the structured upstream data.
   - `metadata.research_step.input_instructions` for the full task prompt.
   - `metadata.research_step.output_instructions` for what the output must contain.

   If `input.md` or `input.json` is missing (e.g., on a task created by an older plan run), fall back to gathering upstream context inline: read each upstream task's `output.json` and the first few paragraphs of its `output.md`, and proceed.

5. **Do the work.** The agent produces:
   - `.asta/tasks/<id>/output.md` — the narrative artifact.
   - `.asta/tasks/<id>/output.json` — the structured output (matches the task type's schema in `assets/schemas.yaml`).
   - Any task-type-specific sidecar files referenced from `output.json` (e.g., `extraction_schema.json`, `theories.json`).

   If the task type has an `execute_ref` field in `assets/schemas.yaml`, that's the asta CLI subcommand to invoke. Use it directly; do not fall back to `send-message` without setting the right `skill_id` (that routes to the agent's default task, which is usually the wrong granularity).

6. **Validate structurally.** Run:
   ```
   scripts/validate-output.sh <task_type> .asta/tasks/<id>/output.json
   ```
   Exit 0 ⇒ valid; any non-zero ⇒ fail loudly and **leave the issue `in_progress`** for retry. Do not close.

7. **Persist output pointers.** Build a metadata JSON adding `output_md` and `output_json` fields and `bd update <id> --metadata @<path>`. Preserve all existing fields.

8. **Close.** `bd close <id>`.

9. **Hand off to plan or update-summary.** Decide based on the closed task's `task_type`:

    | Closed task_type | Hand off to |
    |---|---|
    | `literature_review`, `hypothesis`, `analysis`, `synthesis` | **plan** (with this issue as the source). `plan` then chains to **update-summary**. |
    | `auto_discovery`, `extraction_schema_design`, `theorizer_extraction`, `theory_generation`, `grounded_theory_generation`, `novelty_assessment` | **plan** (with this issue as the source). |
    | `scope`, `definitions`, `experiment_design`, `evidence_gathering` | **update-summary** directly. |

    Either path ends with `summary.md` rebuilt.

## Special case: report-kind synthesis

If the closed task is `synthesis(config.run_kind=report)`, additionally create a project-root `report.md` symlink (or copy on platforms without symlink support) pointing at this task's `output.md`. This surfaces the closing deliverable at the conventional location for the user.

```
ln -sf .asta/tasks/<id>/output.md report.md
```

Then proceed to **update-summary** as usual (no further plan replan — `synthesis(run_kind=report)` is the terminal node).

## Notes on output files

- `.asta/tasks/<id>/output.json` is the canonical structured output; `validate-output.sh` runs against it.
- `.asta/tasks/<id>/output.md` is the human narrative; it may include markdown hyperlinks to code, figures, log files. These are not auto-indexed in this version of the spec — the human is expected to follow them by hand.
- Sidecar JSON files (`extraction_schema.json`, `theories.json`, `paper_store.json`, `novelty_results.json`) are referenced from `output.json` via `_path` fields. The sidecar contents are themselves loose-typed (their shape is governed by the upstream CLI, not by `validate-output.sh`).

## Out of scope for this workflow

- Validating output *quality* (correctness, novelty, soundness). Schema validation is structural only.
- Caching or skipping work. There is no `repro`. Closed issues stay closed; if a premise changed, re-open or re-create the affected task by hand.
- Updating `summary.md`. That belongs to `update-summary` and runs immediately after this workflow (directly or via `plan`).
- Designing the next set of tasks. That belongs to `plan`.
