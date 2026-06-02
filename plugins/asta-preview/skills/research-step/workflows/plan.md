# Workflow: plan

Create or extend the research graph. Two modes:

- **bootstrap** — no epic yet. Create the mission epic and the template's first tasks from `mission.md` (default template: `hypothesis_driven_research`).
- **replan** — an epic exists. Add the next tasks after one closes.

Always chains to **update-summary** afterward.

## Preconditions

- `bd` installed and `.beads/` initialized — else run **init**.
- **bootstrap**: `mission.md` is non-empty and `scripts/epic-root.sh` says `status: none`. If `mission.md` is missing, send the user to **brainstorm**.
- **replan**: `scripts/epic-root.sh` says `status: found`. A source task passed in (usually by **execute**) is closed with a populated output.

Each task's metadata holds its `task_type`, `inputs` (the bd ids it reads), `output_schema_version`, and `output`. The epic also carries `epic_root: true`.

## Mode selection

Run `scripts/epic-root.sh`. `status: none` → bootstrap. `status: found` → replan, around the closed task the caller named; if none was named, ask which closed task to build on.

## Bootstrap

1. Read `mission.md` (abort to **brainstorm** if missing).
2. Create the epic:
   ```
   bd create --type=epic --title="<one line from mission.md>" --description="$(cat mission.md)"
   bd update <epic-id> --metadata '{"research_step":{"epic_root":true}}'
   ```
3. Create the template's first tasks, in order, up to its first "for each", taking each task's `type` / `inputs` / `skills` from its row. (Default template: `scope` → `definitions` → `literature_review`.)
4. Add edges: `parent-child` to the epic, and `blocks` from each task named in another's `inputs`.

## Replan

The template (named in `mission.md`; default `hypothesis_driven_research`) is the plan. Find the closed task's node in it and create what comes next, taking each new task's `type` / `inputs` / `skills` from its row:

- **Next step:** create the node(s) the diagram points to. Set inputs from the row, block on each, parent to the epic.
- **For each:** if the closed node is the one a "for each" runs over, create one copy of the block's tasks per item.
- **After a for-each:** create the task that follows the block only once every copy has closed; block it on those.
- **Hypotheses** are filled and closed on creation, not executed (see below). Because they close immediately, also create the step that follows each one in the same pass — otherwise nothing is left open for **execute** to pick up. In general, keep creating whatever just came unblocked until the frontier is tasks that need an execute pass.
- Stop when the next tasks already exist or the node is a leaf. If a closed `synthesis` lists `open_questions`, ask the user before adding follow-up hypotheses. Don't add tasks the template doesn't have.

### Filling in hypotheses

A hypothesis has no separate work to execute — its source already states the claim — so fill its output and close it on creation. It still gets the same files on disk as any task (`output.json` and `output.md` under `.asta/tasks/<id>/`).

1. From its source — a `literature_review` gap, or an `auto_discovery` surprising node — write `statement`, `rationale`, `falsifiable_prediction`, and `expected_evidence`.
2. Follow the template's hypothesis row. For `data_driven_theory_generation`, the claim is the node's finding and the `rationale` cites that node by id (it's added to `inputs`) — every hypothesis traces to a specific finding.
3. Write `output.json` and `output.md` (the readable hypothesis; link any law rather than writing a bare `node_x_y`).
4. Check it: `scripts/validate-output.sh hypothesis <metadata-file> .asta/tasks/<id>`.
5. Save the metadata (`scripts/write-meta.sh` + `bd update <id> --metadata @<path>`) and `bd close <id>`.

If a gap is too thin to fill honestly, leave the hypothesis open for a real `execute` pass instead.

## After either mode

Hand off to **update-summary**.

## Not here

Running tasks → **execute**. Setup → **init**. Editing `mission.md` → **brainstorm**. Output quality isn't checked here.
