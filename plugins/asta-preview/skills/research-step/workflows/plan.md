# Workflow: plan

Create or extend the research graph. The single home for "design the next set of typed tasks." Two modes, selected from state:

- **bootstrap** — no epic exists yet. Create the mission epic and the initial frontier (scope, definitions, literature_review) from `mission.md`.
- **replan** — an epic exists. Add downstream tasks based on a recently-closed task's output, or on user direction.

**Per-template override.** Before bootstrap or replan, scan `workflows/plans/*.md` to see if any template's intro section matches `mission.md`'s described intent. If a template matches, **use its bootstrap + replan rules instead of the defaults below.** The default behavior (no template matches) is the hypothesis-driven flow documented here.

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
    "work_dir": ".asta/<task_type>/<slug>/",
    "output_schema_version": 3,
    "output": null
  }
}
```

The mission epic additionally carries `epic_root: true`.

**Choosing the slug.** When creating a task, pick a short kebab-case slug
that names the *specific instance* (not the task type — the type is
already in the path). Examples:

| task_type | sensible slugs |
|---|---|
| `scope` | `aar-ela`, `glacier-mass-balance` |
| `definitions` | `aar-ela-terms` |
| `literature_review` | `provenance`, `theme-a-aar-geometry`, `theme-b-ela-bands` |
| `autods_run` | the autodiscovery run id (e.g. `9fc65db8`) |
| `replication` | `cross-dataset`, `cross-year`, `2026-05-otto-zeller` |
| `theorize` | `cross-cutting-mechanisms` |
| `autods_synthesis` | `findings` |

After `bd create` returns the new id, `mkdir -p .asta/<task_type>/<slug>/`
so executors can write into it immediately.

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
3. **Create the initial frontier.** Three `task` issues with the metadata
   convention above. Every `bd create` call must include both `--title` and
   `--description`, written per `SKILL.md §"Voice for titles and descriptions"`
   — imperative phrase ≤ 6 words for the title (e.g. "Frame the Alaska
   glacier question", "Define the geometry terms we'll use"); one short
   paragraph in plain ELI-college English for the description.

   Initial frontier:
   - `scope` — `inputs: []`
   - `definitions` — `inputs: [<scope-id>]`
   - `literature_review` — `inputs: [<scope-id>, <definitions-id>]`
4. **Add edges.**
   - `parent-child` from each frontier task to the epic
   - `blocks`: scope → definitions; scope → literature_review; definitions → literature_review
5. **Report.** Print the epic ID and the three task IDs.

## Replan mode

Read the source task's `task_type` and `metadata.research_step.output`. Apply this table. Every newly-created task gets both `--title` and `--description` per the voice rules in `SKILL.md` — descriptions are the primary surface in the UI.



| Source task_type | Action |
|---|---|
| `literature_review` | For each gap in `output.gaps`, create a `hypothesis` task with `inputs: [<scope-id>, <source-id>]`. Edges: `parent-child` to epic; `blocks` from the source. |
| `hypothesis` | Create the chain `experiment_design` → `evidence_gathering` → `analysis`, each `blocks` the next. `experiment_design` depends on the hypothesis (via `inputs`); `analysis` depends on both the hypothesis and the new `evidence_gathering`. All three get `parent-child` to the epic. |
| `analysis` | If every `hypothesis` in the epic now has a closed `analysis`, create one `synthesis` task with `inputs` listing all analysis IDs and the scope ID. `parent-child` to epic; `blocks` from each analysis. Otherwise no-op. |
| `synthesis` (or any `*_synthesis` closing task) | If `output.open_questions` is non-empty, **stop and ask the user** before creating new `hypothesis` tasks; if approved, create them with `discovered-from` edges back. Otherwise no replan — the synthesis is the closing artifact. |
| `scope`, `definitions`, `experiment_design`, `evidence_gathering` | No replan. Report no-op and stop. |

If invoked without a source task and the user has not specified what to plan, do not invent work — ask, or stop.

## After either mode

Hand off to **update-summary** so `summary.md` reflects the new state.

## Out of scope

- Running tasks or producing outputs. That belongs to **execute**.
- Environment setup (installing `bd`/`jq`, `bd init`). That belongs to **init**.
- Editing `mission.md`. That belongs to **brainstorm**.
- Validating output quality.
