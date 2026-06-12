# Workflow: plan

Create or extend the research graph. The flow chains live in `assets/schemas.yaml` (`flows`) — plan reads them, it does not hardcode the sequence. Two modes:

- **bootstrap** — no epic yet: pick a flow and lay its first step(s).
- **replan** — an epic exists: after a step closes, add the next step(s) in its flow chain.

Always chains to **update-summary** afterward.

## Preconditions

- `bd` installed and `.beads/` initialized (else run **init**).
- **bootstrap**: `mission.md` exists; no epic yet (`scripts/epic-root.sh` → `none`).
- **replan**: an epic exists; either `execute` supplied the closed source task, or the user named what to extend.

## Task metadata

Create task leaves with `scripts/create-task.sh <parent> <task_type> <flow> "<title>" "<brief-description>" [input-id ...]`. It sets `metadata.research_step = {flow, task_type, inputs, output_schema_version, output_json: null, output_markdown: null}` and a **brief one-line `description`** (it rejects a missing, multi-line, or over-long description). `execute` later publishes `output_json` (the structured result) and `output_markdown` (the narrative) via `close-task.sh`; the description is not overwritten. The epic carries `epic_root: true`; group nodes (loops, fan-outs, branches) are epics created with `bd create --parent <parent> -t epic` (no task_type, no description rules). A session may run several flows — the flow is per task, not per epic.

## Indentation is the tree

The flow in `assets/schemas.yaml` is an indented outline, and the beads graph you build **is that same outline**: each indentation level in the flow becomes one parent-child level in beads. Build it with `bd create --parent`, walking the flow top-down, so hierarchical ids (`wf`, `wf.1`, `wf.1.1`, …) encode the outline position. There are **no `blocks`/`deps` edges** — ordering is the id order, because you create nodes in the order they run.

Reading a flow node:

- A node with a `chain` is a **step** → a `task` issue tagged with its `task_type`.
- A node without a `chain` (only child nodes and a `mission`) is a **group** → a non-executable `epic` issue (a flow, a loop, or a fan-out). The keys `mission` and `chain` are never nodes.
- A `chain` item of the form `{workflow: <flow>, mission: <text>}` expands that node into the named sub-flow's own tree.
- A **fan-out group** (`replication`, `theory_generation`, `verification`) inserts **one branch level per item**: the group node, then one branch epic per item, then the group's steps repeated under each branch. The group `mission` names what to branch on.

The reproduction flow therefore produces this tree (ids illustrative; `[group]` nodes are epics, leaves are tasks):

```
wf                      [epic]    <mission>
 wf.1                   [loop]    reproduction
  wf.1.1                          data_driven_discovery
  wf.1.2                          law_extraction
  wf.1.3                          evidence_gathering
  wf.1.4                [fan-out] replication            one branch per law
   wf.1.4.1             [branch]  <law>
    wf.1.4.1.1                    reproduction_design
    wf.1.4.1.2                    analysis
    wf.1.4.1.3                    reproduction_audit
    wf.1.4.1.4                    reproduce
   wf.1.4.2             [branch]  <law> …
  wf.1.5                          reproduction_synthesis
```

The composed flow nests the same way: `wf.1` data_provenance, `wf.2` reproduction, `wf.3` theorizer, `wf.4` verification (one branch per testable theory), `wf.5` verification_synthesis, `wf.6` gap_synthesis, `wf.7` final_synthesis. Each sub-flow ends in its own synthesis step that emits a report (provenance_report, reproduction_report, theory_report, verification_report); gap_synthesis aggregates their gaps into data_gaps_report and final_synthesis writes the theory-led research_report.

## Ordering and closing (no edges)

- **Next task = the open issue with a `task_type` and the smallest id.** Groups (no `task_type`) are never executed.
- Because you create in execution order, sequential steps sort before later ones; parallel branches (`wf.1.4.1`, `wf.1.4.2`, …) are independent so any order is fine; a fan-in step like `reproduction_synthesis` (`wf.1.5`) is created after its branches, so it sorts last.
- A group closes when its last child closes — `scripts/close-task.sh` does this automatically, walking up and closing each ancestor whose children are all closed. Never close groups by hand.

## Static vs data-dependent fan-outs

- **Static** (`theory_generation` by objective): both branches are known up front → create them together.
- **Data-dependent** (`replication` per law, `verification` per testable theory): the branch set is known only after the upstream step closes (`law_extraction`, `testability_triage`). Lay only what you can; `execute` closes the upstream step; then replan reads its output and creates the branches under the group. Never pre-create data-dependent branches. For any branch the data cannot support, record why rather than dropping it.

## Gates (replan)

- When `reproduction_design` closes: `feasibility` of `feasible`/`proxy_only` → create `analysis`, `reproduction_audit`, `reproduce` under that branch; `data_unavailable`/`construct_mismatch` → create only `reproduce` (it records the law `outcome: n/a`, `testability: untestable`) plus a `data_acquisition` task under the branch holding the gap. No analysis is created.
- When `testability_triage` closes: create a `verification` branch only per theory in `testable_theory_ids`; the rest become `next_steps` in the final report.

## Bootstrap

1. Read `mission.md`. **Pick a flow** from `flows` that fits it (or compose your own chain of `tasks`); ask the user if it's unclear.
2. `bd create -t epic` the root from the mission, tagged `epic_root: true` + the flow. Create each loop/group epic with `bd create --parent <its parent>` as you reach it, so the id hierarchy matches the flow's indentation.
3. **Create the frontier — and only the frontier.** Lay the flow's first step(s) with `scripts/create-task.sh <group> <task_type> <flow> "<title>" "<brief-description>" [input-id ...]` (a brief one-line description is required). **No edges.** Do not pre-create downstream steps or data-dependent branches; replan adds them once their inputs close.
4. Report the epic id, the flow, the loop/group ids, and the frontier task ids.

## Replan

When a step closes, create the next node(s) under their parent, in flow order:

- Create each step with `create-task.sh` (its `inputs` are the upstream issue ids it reads, for `execute`'s input-gathering — not for scheduling).
- A fan-out group: `bd create --parent <group> -t epic` one branch epic per item, then the group's steps under each via `create-task.sh` (record why for any branch the data can't support, rather than skipping it).
- Apply the **Gates** rules above.
- The closing synthesis of a sub-flow (`provenance_synthesis`, `reproduction_synthesis`, `theory_synthesis`, `verification_synthesis`) is created after its branches, so it sorts last; `gap_synthesis` and `final_synthesis` sort after all sub-flows. These are distinct task types, each with its own report output shape (provenance_report, reproduction_report, theory_report, verification_report, data_gaps_report, research_report).

Stop at the end of the flow. If the closed step has nothing downstream, report no-op.

## After either mode

Hand off to **update-summary**. There are no edges to verify — the parent-child tree is the whole structure.

## Out of scope

- Running tasks or producing outputs (**execute**).
- Environment setup (**init**); editing `mission.md` (**brainstorm**); judging output quality.
