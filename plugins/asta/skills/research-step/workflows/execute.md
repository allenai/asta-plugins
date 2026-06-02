# Workflow: execute

Run one ready task end-to-end. Loads its schema, gathers its declared inputs, produces a structured output, validates it, and closes the issue. After closing, hands off to **plan** if the closed task type unlocks new graph structure; otherwise hands off to **update-summary**.

## Preconditions

- An epic root exists (`scripts/epic-root.sh` prints `status: found`).
- `bd ready --json` is non-empty, **or** the caller supplied a specific task ID that is currently `open` and unblocked.

## Steps

1. **Pick a task.** If a task ID was supplied, use it. Else `bd ready --json` and pick the oldest issue (tiebreak by `bd-id` ascending).
2. **Claim it.** `bd update <id> --status=in_progress`.
3. **Load the schema.** Read `metadata.research_step.task_type` from the issue. Open `assets/schemas.yaml` and find the matching entry under `task_types`. **If the task type isn't one of the 8 standard types** (`scope`, `definitions`, `literature_review`, `hypothesis`, `experiment_design`, `evidence_gathering`, `analysis`, `synthesis`), scan `workflows/plans/*.md` for the template that defines this task type and follow its `### <task_type>` section for execution prose (CLI commands, paths, parsing details, fallback handling).
4. **Resolve the work_dir.** Read `metadata.research_step.work_dir`. Every file this task writes goes under that directory. The directory should already exist from `plan`'s create step; `mkdir -p "$work_dir"` is a safe no-op. Filenames inside follow `assets/schemas.yaml > file_conventions` for the task type — write `summary.md` for `literature_review`, `findings.md` for `autods_synthesis`, etc.
5. **Gather inputs.** Read the `metadata.research_step.output` of every issue listed in this issue's `inputs`. For each upstream task, also walk its `work_dir` directly (e.g., open `<upstream.work_dir>/summary.md`) when the prose context matters. **This is the only context to use** — do not pull in unrelated repo state.
5a. **Steering pickup.** Also `bd show <current-task-id> --json` and inspect `comments[]`. For every comment **authored by someone other than `claude`/`agent`** (per `author` regex `/^(claude\|agent)/i`) that was created **since the most recent agent-authored comment on this task** (or since the task was created, whichever is later), treat it as a steering note. The agent decides how to respond — acknowledge inline (`bd comment add <id> "<reply>" --author claude`), adjust the plan, or note explicitly why it cannot apply. Do not silently ignore.
6. **Do the work.** Write the structured output as a JSON object matching the schema. Write supporting files (markdown reports, JSON dumps, scripts, figures) inside `work_dir` per the file convention. Markdown files follow the inline-citation rule in `SKILL.md §"Markdown convention"`.
7. **Validate structurally.** Run `scripts/validate-output.sh <task_type> <metadata-json-file>`. It checks the envelope (`research_step.task_type`, `inputs`, `work_dir`, `output`) and every required `output.<key>` for the task_type, plus type spot-checks for the high-leverage cases (e.g., `analysis.verdict` enum, `analysis.confidence` range). Exit 0 ⇒ valid. Any non-zero exit ⇒ fail loudly and **leave the issue `in_progress`** for retry. Do not close.
8. **Persist the output.** Materialize the metadata JSON via `scripts/write-meta.sh` (reads JSON from stdin, prints a temp file path), then `bd update <id> --metadata @<path>`. Preserve the existing `task_type`, `inputs`, and `work_dir`.
9. **Write a one-line `close_reason`.** A single short sentence stating what
   was produced, in the plain-English voice from
   `SKILL.md §"Voice for titles and descriptions"` (same ELI-college reader,
   no jargon up front, no internal labels). Used in summary digests and
   `bd list` output; not rendered in the Asta Flows panel. Avoid empty
   placeholders (`"completed"`, `"done"`, `""`) — they aren't useful to
   humans scanning the log.
10. **Close.** `bd close <id> --reason "<one-line summary>"`.
11. **Hand off to plan or update-summary.** Some closed task types unlock new graph structure; others don't. Decide based on the closed task's `task_type`:

    | Closed task_type | Hand off to |
    |---|---|
    | `literature_review`, `hypothesis`, `analysis`, `synthesis`, `*_synthesis` | **plan** (with this issue as the source). `plan` then chains to **update-summary**. |
    | `scope`, `definitions`, `experiment_design`, `evidence_gathering` | **update-summary** directly. |

    Either path ends with `summary.md` rebuilt.

## Out of scope for this workflow

- Validating output *quality* (correctness, novelty, soundness). Schema validation is structural only.
- Caching or skipping work. There is no `repro`. Closed issues stay closed; if a premise changed, re-open or re-create the affected task by hand.
- Updating `summary.md`. That belongs to `update-summary` and runs immediately after this workflow (directly or via `plan`).
- Designing the next set of tasks. That belongs to `plan`.
