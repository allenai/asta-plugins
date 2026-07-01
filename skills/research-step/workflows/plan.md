# Workflow: plan

Create or extend the research graph. The workflows live in `assets/workflows.yaml` (`workflows`) — plan reads them, it does not hardcode the sequence. Two modes:

- **bootstrap** — no epic yet: pick a flow and lay its first step(s).
- **replan** — an epic exists: after a step closes, add the next step(s) in its flow chain.

Always chains to **update-summary** afterward.

## Preconditions

- `bd` installed and `.beads/` initialized (else run **init**).
- **bootstrap**: `mission.md` exists; no epic yet (`scripts/epic-root.sh` → `none`).
- **replan**: an epic exists; either `execute` supplied the closed source task, or the user named what to extend.

## Task metadata

Create task leaves with `scripts/create-task.sh <parent> <task_type> <flow> "<title>" "<brief-description>" [input-id ...]`. It sets `metadata.research_step = {flow, task_type, inputs, output_schema_version, output_json: null}` and a **brief one-line `description`** (it rejects a missing, multi-line, or over-long description). `execute` later publishes `output_json` (the structured result) via `close-task.sh`; the description is not overwritten. The epic carries `epic_root: true`; group nodes (workflows, fan-outs, branches) are epics created with `bd create --parent <parent> -t epic` (no task_type, no description rules). A session may run several flows — the flow is per task, not per epic.

## Indentation is the tree

The flow in `assets/workflows.yaml` is an indented outline, and the beads graph you build **is that same outline**: each indentation level in the flow becomes one parent-child level in beads. Build it with `bd create --parent`, walking the flow top-down, so hierarchical ids (`wf`, `wf.1`, `wf.1.1`, …) encode the outline position. There are **no `blocks`/`deps` edges** — ordering is the id order, because you create nodes in the order they run.

How to read a flow node (step vs group vs `child_workflows` composition vs `replan` fan-out) is documented in `assets/README.md`. The build-specific rule: a **fan-out group** (`replication`, `testing`) inserts **one branch level per item** — the group node, then one branch epic per item, then the group's steps repeated under each branch; the group `mission` names what to branch on.

The reproduction flow therefore produces this tree (ids illustrative; `[group]` nodes are epics, leaves are tasks):

```
wf                      [epic]    <mission>
 wf.1                   [loop]    reproduction
  wf.1.1                          auto_discovery
  wf.1.2                          evidence_gathering
  wf.1.3                [fan-out] replication            one branch per law
   wf.1.3.1             [branch]  <law>
    wf.1.3.1.1                    experiment_design
    wf.1.3.1.2                    analysis
    wf.1.3.1.3                    audit
   wf.1.3.2             [branch]  <law> …
```

The composed flow nests the same way: `wf.1` data_provenance, `wf.2` reproduction, `wf.3` theorizer. Flows **terminate at their last data-producing step** — there is no synthesis step. The whole-session report is rendered deterministically by `scripts/compile-report.py` at session end (run by **update-summary** once no open tasks remain), joining the closed tasks' typed records; it is not a task.

## Ordering and closing (no edges)

- **Next task = the `next:` line of `scripts/next-task.sh`** (open issues with a `task_type`, **numerically** sorted by hierarchical id — `wf.1.2` before `wf.1.10`). Groups (no `task_type`) are never executed. `execute` and `update-summary` both use this script, so they never disagree about what runs next.
- Because you create in execution order, sequential steps sort before later ones; parallel branches (`wf.1.3.1`, `wf.1.3.2`, …) are independent so any order is fine. There is no fan-in step — a fan-out group closes when its last branch closes, and the session report is compiled after all tasks close.
- A group closes when its last child closes — `scripts/close-task.sh` does this automatically, walking up and closing each ancestor whose children are all closed. It never closes the **epic root**: "root open, no open tasks" is the session-complete state. Never close groups by hand.

## Data-dependent fan-outs

- Every fan-out is **data-dependent** (`replication` per law, `testing` per hypothesis): the branch set is known only after the upstream step closes (`auto_discovery`, `hypothesis_formation`). Lay only what you can; `execute` closes the upstream step; then replan reads its output and creates the branches under the group. Never pre-create data-dependent branches. For any branch the data cannot support, record why rather than dropping it.

## Gates (replan)

- When `experiment_design` closes (a `replication` or `testing` branch): `feasibility` of `feasible`/`proxy_only` → create the branch's remaining steps — in `testing`, also `data_acquisition` when the design names data not yet in hand — i.e. `[data_acquisition,] analysis`, `audit`; `data_unavailable`/`construct_mismatch` → create only `audit`, wired to `[experiment_design]` alone, which records `outcome: n/a`, `testability: untestable`, and the reproduction signal from the design. No `analysis` is created — the gap already lives on the closed `experiment_design`.
- When `hypothesis_formation` closes: create one `testing` branch per hypothesis.

## Bootstrap

1. Read `mission.md`. **Pick a workflow** from `workflows` that fits it (or compose your own from `tasks`); ask the user if it's unclear.
2. **Resolve the session config.** Start from the `config:` defaults in `assets/workflows.yaml`; apply any overrides from a `## Config` section in `mission.md` (one `key: value` line each; unknown keys are an error — surface them). The resolved map is pinned in the next step and never re-resolved mid-session.
3. `bd create -t epic` the root from the mission, tagged with metadata `{"research_step": {"epic_root": true, "flow": "<flow>", "config": {<resolved config>}}}`. Create each loop/group epic with `bd create --parent <its parent>` as you reach it, so the id hierarchy matches the flow's indentation.
4. **Create the frontier.** Lay the first workflow's steps with `scripts/create-task.sh <group> <task_type> <flow> "<title>" "<brief-description>" [input-id ...]` (a brief one-line description is required). **No edges.** A linear workflow's sequential steps are statically wired and all known up front, so create them together — otherwise closing the lone step auto-closes the whole group (close-task.sh walks up and closes any ancestor whose children are all closed). Defer only **data-dependent fan-out branches** (`replication` per law, `testing` per hypothesis), whose branch count is unknown until the upstream step closes; replan adds those once their inputs close.
5. Report the epic id, the flow, the resolved config, the loop/group ids, and the frontier task ids.

## Replan

When a step closes, create the next node(s) under their parent, in flow order:

- Create each step with `create-task.sh`. Its `inputs` are the upstream issue ids it reads, for `execute`'s input-gathering — not for scheduling; the step's `input:` list in `workflows.yaml` names **which** upstream steps to wire.
- A fan-out group: `bd create --parent <group> -t epic` one branch epic per item, then the branch steps under each via `create-task.sh` — **but a gated group lays only the steps up to its gate**: under a `replication` or `testing` branch create only `experiment_design`; the Gate below creates the rest when it closes. Record why for any branch the data can't support, rather than skipping it.
- Apply the **Gates** rules above — they are the only creator of post-gate steps, so nothing is double-created.
- There is no synthesis step to create — flows end at their last data-producing step. Once a flow's branches and steps have all closed, the session is complete (root open, no open tasks) and **update-summary** renders the report.

Stop at the end of the flow. If the closed step has nothing downstream, report no-op.

## After either mode

Hand off to **update-summary**. There are no edges to verify — the parent-child tree is the whole structure.

## Out of scope

- Running tasks or producing outputs (**execute**).
- Environment setup (**init**); editing `mission.md` (**brainstorm**); judging output quality.
