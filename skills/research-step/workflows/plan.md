# Workflow: plan

Create or extend the research graph. The single home for "design the next set of typed tasks." Two modes, selected from state:

- **bootstrap** — no epic exists yet. Create the mission epic and the initial frontier (scope, definitions, literature_review) from `mission.md`.
- **replan** — an epic exists. Add downstream tasks based on a recently-closed task's output, or on user direction.

Always chains to **update-summary** afterward so `summary.md` reflects the new graph.

## Preconditions

- `bd` is installed and `.beads/` is initialized. If not, run **init** first.
- For **bootstrap**: `mission.md` exists and is non-empty, and `scripts/epic-root.sh` reports `status: none` (no epic yet). If `mission.md` is missing, abort and route the user to **brainstorm** to draft one.
- For **replan**: `scripts/epic-root.sh` reports `status: found` (an epic exists). If a specific source task was supplied (typically by `execute` chaining into this workflow), it is closed and has a populated `metadata.research_step.output`.

## Issue metadata convention

Every task issue carries:

```json
{
  "research_step": {
    "task_type": "<scope|definitions|literature_review|hypothesis|experiment_design|evidence_gathering|analysis|synthesis>",
    "inputs": ["bd-xxxx", "bd-yyyy"],
    "output_schema_version": 1,
    "output": null
  }
}
```

The mission epic additionally carries `epic_root: true`.

## Mode selection

1. Run `scripts/epic-root.sh`. `status: none` → **bootstrap**.
2. `status: found` (epic ID on the `id:` line) → **replan**. If the caller named a specific closed task (typical when `execute` chains here), use it as the source. Else, ask the user which closed task to plan around or which subgraph to extend, then proceed.

## Bootstrap mode

1. **Verify mission.** Read `mission.md`. If missing or empty, abort and suggest **brainstorm**.
2. **Create the epic.**
   ```
   bd create --type=epic --title="<one-line summary of mission.md>" --description="$(cat mission.md)"
   bd update <epic-id> --metadata '{"research_step":{"epic_root":true}}'
   ```
3. **Create the initial frontier.** Three `task` issues with the metadata convention above:
   - `scope: <one-line>` — `inputs: []`
   - `definitions: <one-line>` — `inputs: [<scope-id>]`
   - `literature_review: <one-line>` — `inputs: [<scope-id>, <definitions-id>]`
4. **Add edges.**
   - `parent-child` from each frontier task to the epic
   - `blocks`: scope → definitions; scope → literature_review; definitions → literature_review
5. **Report.** Print the epic ID and the three task IDs.

## Replan mode

Read the source task's task_type and output:

```
bd show <source-id> --json | jq '.[0].metadata.research_step.task_type'
bd show <source-id> --json | jq '.[0].metadata.research_step.output'
```

Apply this table:

| Source task_type | Action |
|---|---|
| `literature_review` | For each gap in `output.gaps`, create a `hypothesis` task with `inputs: [<scope-id>, <source-id>]`. Edges: `parent-child` to epic; `blocks` from the source. **Populate `metadata.research_step.output` at creation time** (see below) and close the issue immediately — the gap text already contains the statement, rationale, and prediction in prose, so there is no separate `execute` pass for hypotheses. |
| `hypothesis` | Create the chain `experiment_design` → `evidence_gathering` → `analysis`, each `blocks` the next. `experiment_design` depends on the hypothesis (via `inputs`); `analysis` depends on both the hypothesis and the new `evidence_gathering`. All three get `parent-child` to the epic. |
| `analysis` | If every `hypothesis` in the epic now has a closed `analysis`, create one `synthesis` task with `inputs` listing all analysis IDs and the scope ID. `parent-child` to epic; `blocks` from each analysis. Otherwise no-op. |
| `synthesis` | If `output.open_questions` is non-empty, **stop and ask the user** before creating new `hypothesis` tasks. If approved, create them with a `discovered-from` edge back to the synthesis (in addition to the usual edges). |
| `scope`, `definitions`, `experiment_design`, `evidence_gathering` | No replan. Report no-op and stop. |

If invoked without a source task and the user has not specified what to plan, do not invent work — ask, or stop.

### Auto-resolving hypothesis tasks

When creating a `hypothesis` from a literature_review gap:

1. Derive the four output fields directly from the gap text and surrounding `literature_review` output (`bd show <source-id> --json | jq '.[0].metadata.research_step.output'`):
   - `statement` — `H_n: <one-sentence claim>`
   - `rationale` — why this gap implies the claim
   - `falsifiable_prediction` — what observation would refute it
   - `expected_evidence` — list of concrete evidence types that would support it
2. Validate with `scripts/validate-output.sh hypothesis <metadata-json-file>` before persisting.
3. Persist with `scripts/write-meta.sh` + `bd update <id> --metadata @<path>`, then `bd close <id>`.

If a gap is too thin to fill these fields without inventing content, **do not auto-resolve** — leave the hypothesis open and surface it to the user. Genuine ambiguity is the one case where a separate `execute` pass is warranted.

## After either mode

Hand off to **update-summary** so `summary.md` reflects the new state.

## Out of scope

- Running tasks or producing outputs. That belongs to **execute**.
- Environment setup (installing `bd`/`jq`, `bd init`). That belongs to **init**.
- Editing `mission.md`. That belongs to **brainstorm**.
- Validating output quality.
