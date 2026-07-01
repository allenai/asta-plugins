# Workflow: execute

Run one ready task end-to-end. Loads its schema, gathers its declared inputs, produces a structured output, validates it, and closes the issue. After closing, hands off to **plan** if the closed task type unlocks new graph structure; otherwise hands off to **update-summary**.

## Preconditions

- An epic root exists (`scripts/epic-root.sh` prints `status: found`).
- An open issue with a `task_type` exists, **or** the caller supplied a specific `open` task ID.

## Steps

1. **Pick a task.** If a task ID was supplied, use it. Else run `scripts/next-task.sh` and take the `next:` id — it is the single definition of ordering (open issues with a `task_type`, numerically sorted by hierarchical id; `update-summary` renders the same order). `next: none` ⇒ report that and stop. Grouping issues (epics, no `task_type`) are never executed; `close-task.sh` closes them when their last child closes. Do not use `bd ready` — there are no dependency edges, so id order is the ordering signal.
2. **Check readiness.** For every issue id in this task's `inputs` (`bd show <id> --json | jq '.[0].metadata.research_step.inputs'`), verify it is `closed` with a non-null `output_json`. If any input is not ready, **stop and report it** — the graph was built out of order (a task left `in_progress`, or a replan misordering); do not improvise the missing input. This is the readiness check that dependency edges used to provide.
3. **Claim it.** `bd update <id> --status=in_progress`.
4. **Load the schema and config.** Read the flow and task type with `bd show <id> --json | jq -r '.[0].metadata.research_step | .flow, .task_type'`. In `assets/schemas.yaml`: the task's output shape is `tasks.<task_type>.output` (a mapping of key → type; `[type]` means a JSON array of that type); find the step inside `flows.<flow>` — it may be nested under a fan-out group (e.g. `flows.reproduction.replication.experiment_design`) — and use its `mission`, `input`, and `chain`. Read the **session config** pinned on the epic root (`bd show <epic-id> --json | jq '.[0].metadata.research_step.config'`) and pass its values into the chain where they apply — `n_experiments` into the run-metadata JSON for `asta autodiscovery metadata`, `max_papers_to_retrieve` on `asta generate-theories find-and-extract`. Do not re-read defaults from schemas.yaml mid-session; the pin is the truth. (Sessions bootstrapped before config pinning exist: an absent pin means use the schemas.yaml defaults.)
5. **Gather inputs.** For every issue listed in this issue's `inputs`, read its output with `bd show <input-id> --json | jq '.[0].metadata.research_step.output_json'`. Also load `mission.md` and any files referenced from input outputs via `_path` fields (e.g., `report_path` from `reproduction_synthesis`). **This is the only context to use** — do not pull in unrelated repo state.
6. **Do the work.** Follow the step's `mission` and run its `chain` (the asta commands). Produce two things:
   - **`output_json`** — a JSON object holding exactly the schema's output keys for this task (`tasks.<task_type>.output`), and nothing else. Fill every typed field the schema declares (including typed verdicts like `adjudication.outcome` or `audit_report.verdict_survives`); only values with **no typed field** (an execution id, intermediate file paths, raw tool output) go in `artifacts`. Artifact rows are **A2A 1.0 Artifacts** — `{artifactId, name, description, parts, metadata}`, where `parts` is an array of text / file / data parts (see `artifact` and `part` in the schema). Artifacts returned by chain commands are stored as received (their kind in `metadata.type`); locally produced byproducts (a figure, a script, a data file) are wrapped as file parts in the uri form — repo-root-relative path plus mimeType — never the bytes form (beads' ~64KB cap). Records are immutable — emit verdicts and enrichments as their own records referencing the original by id (`adjudication.subject_id`, `source_access.data_source_id`); never re-emit an upstream record with changed values. Keep it slim: beads stores metadata inline and rejects large blobs (~64KB+), so put heavy data (raw agent JSON, datasets, full extractions) under `.asta/<agent>/<slug>/` and reference it by repo-root-relative path. `<agent>` is the asta command group (`literature`, `generate-theories`, `autodiscovery`, `analyze-data`); `<slug>` is `YYYY-MM-DD-<short-query-slug>`. Preserve evidence uuids that tie a finding back to its paper. For schema fields ending in `_path`, write the file first and put the path in the JSON.
   - **`output_markdown`** — a concise write-up of the result, one `## <key>` section per output key, following the **Report conventions** below (entity hyperlinks, tables, figures). This is guidance, not a gate — the scripts do not assert style. Keep it a digest; heavy data stays in the artifact files.
7. **Finish with `close-task.sh`.** Write the two files — `output.json` (the `output_json` object) and `output.md` (the `output_markdown`) — then run `scripts/close-task.sh <id> <output.json> <output.md>`. It publishes both into the issue metadata, validates `output_json` structurally against the schema (keys must equal the keys of `tasks.<task_type>.output` — which always include `artifacts` — none null; no style checks), closes the issue, confirms it closed, and closes any ancestor group whose last child just closed (it never closes the epic root — the session-complete state is root open with no open tasks). A non-zero exit **before** the `closed <id>` line means the issue is still `in_progress` — fix and re-run. A warning **after** `closed <id>` means the task closed but a group could not be auto-closed; close that group manually. The `description` is untouched; it stays the brief one-liner set at creation.
8. **Hand off.** If the flow has steps after this one, hand off to **plan** (source = this issue) to create them; plan chains to **update-summary**. If this was the flow's final synthesis, hand off to **update-summary** directly.

## Report conventions

These apply to every `output_markdown` and to every `*_synthesis` report deliverable. Rigorous but not over the top: a report stays roughly 50–100 lines; the detail behind it lives in artifacts it links to.

- **Every named entity is a hyperlink.** Papers → DOI or canonical Semantic Scholar URL; datasets and result files → relative path; runs/experiments → their artifact or metadata file; laws/theories/hypotheses → their ledger row, written with an anchor (`<a id="l1"></a>`) so other reports can deep-link (`reproduction_report.md#l1`). A named thing with no link is a defect.
- **Tables are the spine.** Any ledger, matrix, or catalog (laws × outcomes, theories × verdicts, sources × access) is a table with one row per record, mirroring the typed rows in `output_json`.
- **Figures carry the quantitative claims.** Embed each one (`![caption](path)`) where the claim is made and list it in the `figures` output field. Analysis-type tasks must emit at least one figure; synthesis reports embed the figures their headline rests on (effect-size comparisons, verdict panels, discovery-vs-holdout shrinkage).
- Neutral, third-person register; numbers in the text match the tables they summarize.

## Notes on output

The structured result is `metadata.research_step.output_json`; the narrative is `metadata.research_step.output_markdown`. The issue **`description`** is the brief one-liner set at creation by `create-task.sh` and is not overwritten. Heavy artifacts live under `.asta/<agent>/<slug>/` where `<slug>` is `YYYY-MM-DD-<short-query-slug>`, referenced by repo-root-relative path (`.asta/<agent>/<slug>/<file>`, repo files like the auto-ds inputs as `inputs/<path>`). `output_json.artifacts` holds A2A Artifacts whose file parts reference those paths by uri; heavy payloads (base64 bytes, raw agent JSON) stay on disk, never inline.

Schema fields ending in `_path` are repo-root-relative paths — write the file before putting the path in `output_json`:

- `report_path` (from every `*_synthesis` report) → the report's `.md` deliverable. The master `final_synthesis` report is typically `report.md` at the repo root; the per-sub-flow reports go under `.asta/<agent>/<slug>/` or alongside it (e.g. `reproduction_report.md`, `theory_report.md`, `verification_report.md`, `hypothesis_report.md`, `data_gaps_report.md`).

If the executor crashes between writing a file and closing the issue, the file is harmless orphan data — re-running `execute` overwrites it.

## Out of scope for this workflow

- Validating output *quality* (correctness, novelty, soundness). Schema validation is structural only.
- Caching or skipping work. There is no `repro`. Closed issues stay closed; if a premise changed, re-open or re-create the affected task by hand.
- Updating `summary.md`. That belongs to `update-summary` and runs immediately after this workflow (directly or via `plan`).
- Designing the next set of tasks. That belongs to `plan`.
