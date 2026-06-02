# Workflow: plan

Create or extend the research graph. The single home for "design the next set of typed tasks." Two modes, selected from state:

- **bootstrap** — no epic exists yet. Create the mission epic and the initial frontier from `mission.md`, per the active template (default `hypothesis_driven_research`).
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
    "task_type": "<scope|definitions|literature_review|hypothesis|experiment_design|evidence_gathering|auto_discovery|analysis|synthesis>",
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
3. **Create the initial frontier.** The active template's first tasks — the nodes up to its first `foreach` — each a `task` issue with the metadata convention above, taking `task_type` and `inputs` from the node's row. (Default template `hypothesis_driven_research`: `scope` → `definitions` → `literature_review`.)
4. **Add edges.** `parent-child` from each task to the epic, and `blocks` from each node named in another's `inputs`.
5. **Report.** Print the epic ID and the created task IDs.

## Replan mode

Read the source task's task_type and output:

```
bd show <source-id> --json | jq '.[0].metadata.research_step.task_type'
bd show <source-id> --json | jq '.[0].metadata.research_step.output'
```

Find the closed task's node in the active template and create what comes next, taking each new task's `task_type` / `inputs` / `skills` from its row:

- **Next step:** create the node(s) the diagram points to. Set `inputs` from the row, a `blocks` edge from each, and `parent-child` to the epic.
- **Foreach:** if the closed node is a `foreach` source, create one copy of the block's tasks per item.
- **Fan-in:** create a node after a `foreach` only once every copy has closed; block it on those.
- **Hypotheses** are filled and closed at creation (see below), so also create the step that follows each one — otherwise nothing is left for `execute`. Keep creating whatever just unblocked until the frontier needs an `execute` pass.
- Stop when the next tasks already exist or the node is a leaf. If a closed `synthesis` lists `output.open_questions`, **stop and ask the user** before creating follow-up `hypothesis` tasks (add a `discovered-from` edge if approved).

If invoked without a source task and the user has not specified what to plan, do not invent work — ask, or stop.

### Auto-resolving hypothesis tasks

When creating a `hypothesis` from a `literature_review` gap or an `auto_discovery` finding — its claim is already stated, so there's no separate `execute` pass, but it still produces `output.json` and `output.md` on disk like any task:

1. Derive the four output fields from the source — the gap text and surrounding `literature_review` output, or the finding (`bd show <source-id> --json | jq '.[0].metadata.research_step.output'`):
   - `statement` — `H_n: <one-sentence claim>`
   - `rationale` — why the source implies the claim (for a finding, cite its node id)
   - `falsifiable_prediction` — what observation would refute it
   - `expected_evidence` — list of concrete evidence types that would support it
2. Write `output.json` and `output.md` under `.asta/tasks/<id>/`, then validate: `scripts/validate-output.sh hypothesis <metadata-json-file> .asta/tasks/<id>`.
3. Persist with `scripts/write-meta.sh` + `bd update <id> --metadata @<path>`, then `bd close <id>`.

If a gap is too thin to fill these fields without inventing content, **do not auto-resolve** — leave the hypothesis open and surface it to the user. Genuine ambiguity is the one case where a separate `execute` pass is warranted.

## After either mode

Hand off to **update-summary** so `summary.md` reflects the new state.

## Not here

Running tasks → **execute**. Setup → **init**. Editing `mission.md` → **brainstorm**. Output quality isn't checked here.
