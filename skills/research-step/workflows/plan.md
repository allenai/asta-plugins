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

## Researcher review protocol

**Plans are proposed before being committed as beads.** This applies to both modes. The flow is:

1. **Check autonomy preference.** If the researcher has explicitly indicated (in this session, or via a `--auto` style 
   instruction, or by saying something like "just do the planning yourself" / "I don't need to review") that they don't 
   want to review, skip directly to commit. Honor this; some replans (e.g., trivial fan-out from a literature_review with obvious gaps) 
   genuinely don't need verification.

2. **Propose plan candidates.** Otherwise, present each candidate task as a bullet with:
   - **Proposed title** (and `task_type`)
   - **Mission dimension(s) addressed** — which exploratory dimension(s) from `mission.md`, and at what priority
   - **Question or gap targeted** — the specific thing this task is meant to resolve
   - **Risks** — scope creep, rabbit holes, blocked dependencies, ambiguity that might force rework
   - **Proposed edges** — parents, blocks, inputs

3. **Iterate.** The researcher may:
   - Edit titles, scopes, or metadata
   - Add tasks the model missed
   - Remove tasks that are off-mission or premature
   - Reorder dependencies
   - Ask clarifying questions

   Loop until the researcher signals consolidation ("looks good", "ship it", "approved", or equivalent).

4. **Final approval list.** Once consolidation is reached, display a **short list** of the final tasks 
   (title + task_type + one-line purpose, no prose) and ask for explicit final approval before any `bd create` calls.

5. **Commit.** Only after final approval, run the `bd create` / `bd update` / edge commands described in the mode sections below.

If the researcher declines the whole plan, stop. Do not create partial graphs.

## Bootstrap mode

1. **Verify mission.** Read `mission.md`. If missing or empty, abort and suggest **brainstorm**.
2. **Draft the plan candidates:**
   - The mission epic (title derived from `mission.md`)
   - `scope: <one-line>` — `inputs: []`
   - `definitions: <one-line>` — `inputs: [<scope>]`
   - `literature_review: <one-line>` — `inputs: [<scope>, <definitions>]`
3. **Run the researcher review protocol** above.
4. **On approval, commit:**
   ```
   bd create --type=epic --title="<one-line summary of mission.md>" --description="$(cat mission.md)"
   bd update <epic-id> --metadata '{"research_step":{"epic_root":true}}'
   ```
5. **Add edges.**
   - `parent-child` from each frontier task to the epic
   - `blocks`: scope → definitions; scope → literature_review; definitions → literature_review
6. **Report.** Print the epic ID and the three task IDs.

## Replan mode

Read the source task's task_type and output:

```
bd show <source-id> --json | jq '.[0].metadata.research_step.task_type'
bd show <source-id> --json | jq '.[0].metadata.research_step.output'
```

Apply this table to **draft candidates** (not yet commit):

| Source task_type | Action |
|---|---|
| `literature_review` | For each gap in `output.gaps`, create a `hypothesis` task with `inputs: [<scope-id>, <source-id>]`. Edges: `parent-child` to epic; `blocks` from the source. **Populate `metadata.research_step.output` at creation time** (see below) and close the issue immediately — the gap text already contains the statement, rationale, and prediction in prose, so there is no separate `execute` pass for hypotheses. |
| `hypothesis` | Create the chain `experiment_design` → `evidence_gathering` → `analysis`, each `blocks` the next. `experiment_design` depends on the hypothesis (via `inputs`); `analysis` depends on both the hypothesis and the new `evidence_gathering`. All three get `parent-child` to the epic. |
| `analysis` | If every `hypothesis` in the epic now has a closed `analysis`, create one `synthesis` task with `inputs` listing all analysis IDs and the scope ID. `parent-child` to epic; `blocks` from each analysis. Otherwise no-op. |
| `synthesis` | If `output.open_questions` is non-empty, **stop and ask the user** before creating new `hypothesis` tasks. If approved, create them with a `discovered-from` edge back to the synthesis (in addition to the usual edges). |
| `scope`, `definitions`, `experiment_design`, `evidence_gathering` | No replan. Report no-op and stop. |

If invoked without a source task and the user has not specified what to plan, do not invent work — ask, or stop.

**Run the researcher review protocol** on the drafted candidates before committing. On approval, create the issues, set metadata, and add edges as specified.

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

Note: the derived hypothesis output fields are *not* part of the planning review — the researcher reviews which hypotheses to create; the auto-resolution content is mechanical derivation. If the researcher wants to review hypothesis content too, they can ask, or run `execute` instead of auto-resolving.

## After either mode

Hand off to **update-summary** so `summary.md` reflects the new state.

## Out of scope

- Running tasks or producing outputs. That belongs to **execute**.
- Environment setup (installing `bd`/`jq`, `bd init`). That belongs to **init**.
- Editing `mission.md`. That belongs to **brainstorm**.
- Validating output quality.
