# Workflow: plan

Create or extend the research graph by reading the epic's chosen YAML template and walking it. **You are the walker.** Read the template directly (via the Read tool), evaluate its constructs as documented below, and issue `bd` commands inline. No separate walker script.

Two modes, selected from state:

- **bootstrap** — no epic exists yet. Create the mission epic and the initial frontier from `template.bootstrap[]`.
- **replan** — an epic exists. Add downstream tasks per `template.replan[<source.task_type>][]`, where `<source.task_type>` is the type of the most-recently-closed task.

Always chains to **update-summary** afterward so `summary.md` reflects the new graph.

## Preconditions

- `bd` is installed and `.beads/` is initialized. If not, run **init** first.
- `mission.md` exists and its frontmatter has a `template:` field naming a valid template. If not, route the user back to **brainstorm**.
- For **bootstrap**: `scripts/epic-root.sh` reports `status: none` (no epic yet).
- For **replan**: `scripts/epic-root.sh` reports `status: found` (an epic exists). If a specific source task was supplied (typical when `execute` chains in), it is `closed` and has populated `.asta/tasks/<source-id>/output.json`.

## Issue metadata convention (v2)

Every task issue carries (in `bd update --metadata` JSON):

```json
{
  "research_step": {
    "task_type": "<scope|definitions|literature_review|hypothesis|experiment_design|evidence_gathering|analysis|synthesis|auto_discovery|extraction_schema_design|theorizer_extraction|theory_generation|grounded_theory_generation|novelty_assessment>",
    "inputs": ["bd-xxxx", "bd-yyyy"],
    "output_schema_version": 2,
    "input_instructions": "<rendered prompt text — see Interpolation below>",
    "output_instructions": "<rendered prompt text>",
    "config": { "<optional flat key/value pairs>": "..." }
  }
}
```

The mission epic additionally carries `epic_root: true` and `template: <template_name>`.

After **execute** has run a task and closed it, the metadata gains `input_md`, `input_json`, `output_md`, `output_json` pointers (set by execute, not by plan).

## Mode selection

1. Run `scripts/epic-root.sh`. `status: none` → **bootstrap**.
2. `status: found` (epic ID on the `id:` line) → **replan**.
   - If the caller named a specific closed task (typical when `execute` chains here), use it as the source.
   - Otherwise, ask the user which closed task to plan around or which subgraph to extend, then proceed.

## Bootstrap mode

1. **Read the template name** from `mission.md` frontmatter:
   ```
   template=$(awk '/^---$/{n++; next} n==1 && /^template:/ {print $2}' mission.md)
   ```
   Open `templates/<template>.yaml` with the Read tool.

2. **Create the epic** (separate from `template.bootstrap[]`). Derive the title from mission.md's first H1 heading; description is the full body. Run:
   ```
   epic_title=$(grep -m1 '^# ' mission.md | sed 's/^# //')
   bd create --type=epic --title="$epic_title" --description="$(cat mission.md)"
   ```
   Capture the returned bd-id (`<epic-id>`). Then set the epic metadata:
   ```
   echo '{"research_step":{"epic_root":true,"template":"<template>"}}' | scripts/write-meta.sh
   bd update <epic-id> --metadata @<the temp path printed by write-meta.sh>
   ```

3. **Create the initial frontier** by walking `template.bootstrap[]` in order. Each entry is a task (NOT another epic). For each entry:
   - Interpolate every `${var}` placeholder in `title`, `input_instructions`, `output_instructions`, and `config` against the bootstrap-time context (see Interpolation below). At bootstrap, the context is just `{mission: <mission.md body>}` plus any explicit fields the template references.
   - `bd create --type=task --title="<title>"`. Capture the returned bd-id.
   - Build the metadata JSON:
     ```json
     {
       "research_step": {
         "task_type": "<task_type>",
         "inputs": ["<resolved bd-ids of upstream tasks listed in `inputs:`>"],
         "output_schema_version": 2,
         "input_instructions": "<interpolated string>",
         "output_instructions": "<interpolated string>",
         "config": <interpolated config object or {}>
       }
     }
     ```
   - Pipe through `scripts/write-meta.sh` and run `bd update <id> --metadata @<path>`.
   - Add edges per the entry's `edges:` or `blocked_by:` field via `bd dep add`.

4. **Report.** Print the epic ID and the frontier task IDs.

## Replan mode

1. **Read the template** as in bootstrap step 1.

2. **Load source-task state.** For the source task ID:
   - `bd show <source-id> --json | jq '.[0].metadata.research_step'` — gives `task_type`, `config`, etc.
   - `cat .asta/tasks/<source-id>/output.json` — gives the structured output.

3. **Look up the replan rules.** `template.replan[<source.task_type>]` is a list of rules. For each rule (in order):

   1. **Evaluate the `when:` predicate** if present. Skip the rule if false. Supported operators in `when:`: `==`, `!=`, `in`, `not`, `and`, `or`, parenthesization, dotted attribute access (e.g., `source.config.run_kind`). No arbitrary code. Names resolved against the **Eval context** below.

   2. **Run the rule's action**:

      - **`create:`** — single `bd create` per the template node (see Creating a task below).
      - **`foreach: <var> in <expr>` + `create:`** — evaluate `<expr>` (typically `source.output_json.gaps`, `source.output_json.themes`, or `upstream.lane_spec.laws`); for each element, set `${var}` in the interpolation context, then create one task.
      - **`foreach_union:`** — a list of `foreach` blocks; create tasks from each in order.
      - **`sequence: [...]` + `blocks: chain`** — create N tasks in order, with `blocks` edges between consecutive entries (so task `n+1` is blocked by task `n`).
      - **`import: <path>` + `with:`** — open `<path>` with the Read tool, substitute the variables in `with:`, and apply the sub-template's `nodes:`.
      - **`ask_user:` block** — present `AskUserQuestion` to the user with one option per key under `options:`. Each option is itself an action block (`create:`, `foreach:`, `sequence:`, `noop: true`, etc.). After the user picks, execute that option's block.
        - Each option may carry a `description:` (shown next to the label) and optional `followup_prompt:`. If `followup_prompt:` is present, call `AskUserQuestion` a second time after the option is picked; the user's free-text reply is bound to `${user_feedback}` in the option's interpolation context.
        - Option labels become the AskUserQuestion option labels verbatim (so `proceed` / `redo` / `append`, or `yes` / `no`, etc. show up as-is).
      - **`noop:`** — do nothing; the rule exists to document a terminal source type.

4. **Avoid duplicate creation.** Before each `bd create`, check `bd list --json` for an issue with the same `(task_type, inputs, config)` triple. If one exists, skip with a brief log line. This makes plan idempotent under partial-failure retry.

5. **Hand off to update-summary.**

## Creating a task (used by `create`, `foreach`, `sequence`, `import`)

1. Resolve `inputs:` — for each name in the list, find the bd-id of the matching closed (or in-progress) task in the epic. Names like `source` refer to the replan source task; `auto_discovery`, `synthesis_across_lanes`, etc. refer to the unique issue of that task_type (or the closest-by-graph-distance one); `all_lane_syntheses`, `all_repro_analyses`, etc. expand to lists of bd-ids matching the convenience predicates.

2. Interpolate every `${var}` placeholder in `input_instructions`, `output_instructions`, `config`, and `title` against the current eval context (which includes loop variables from `foreach`).

3. Build metadata JSON as in Bootstrap step 3 and persist via `scripts/write-meta.sh` + `bd update --metadata`.

4. **Process upstream `output.json` and write `input.md` + `input.json` to the task's working dir.** Create `.asta/tasks/<new-id>/` and:

   a. Read each upstream task's `output.json` file. Compose `input.json` as `{upstream: {<task_type>: <output.json content>}, config: <this issue's config>}`. When multiple upstreams share a task_type, suffix the second / third with `_1`, `_2`.

   b. Write a **short `input.md`** (2-4 sentences) describing what this task is about. It should:
   - Lead with the task type and a one-line context (the theme name, the gap summary, the lane label, etc.).
   - Say what the task does in one or two sentences, with **inline markdown hyperlinks to the upstream `output.md` files** (per the citation convention in `SKILL.md`).
   - End with pointers: `Inputs: see input.json. Full task prompt: input_instructions in beads metadata.`
   - Be a brief, not the full prompt. The full prompt lives in `metadata.research_step.input_instructions` and is what the executing agent works against in **execute**.

   c. Update the metadata to add `input_md` and `input_json` pointers (relative paths to the files written in (a) and (b)), then `bd update --metadata @<path>` again.

5. Add edges per `edges:`. **Important — `bd dep add A B` means "A depends on B" (A is blocked by B). Get the direction right:**
   - `parent_child: epic` → `bd dep add <new-id> <epic-id> --type=parent`  (new task is parented to the epic).
   - `blocks_from: <bd-id-or-list>` → for each upstream U, `bd dep add <new-id> <upstream-id>` (new task depends on U; no `--type` flag — `blocks` is the default).
   - `blocks: chain` (only in `sequence:`) → for consecutive entries in the sequence, `bd dep add <entry-n+1-id> <entry-n-id>` (entry n+1 depends on entry n).
   - `blocked_by: <list>` (used in `bootstrap:`) — same semantics as `blocks_from`: for each upstream U, `bd dep add <new-id> <upstream-id>`.

   To verify direction, after adding the edge, run `bd dep tree <epic-id> --direction up` — children appear indented under the epic (default direction shows what the epic depends on, which is usually nothing).

## Eval context

Available names when evaluating `when:` and `${var}`:

- **`source`** — the closed source task as a dict with:
  - `source.task_type` (string)
  - `source.config` (dict — populated by plan at create time, carried through)
  - `source.output_json` (dict — parsed from `.asta/tasks/<source-id>/output.json`)
  - `source.id` (the bd-id)
- **`epic`** — the epic root, as `{id, metadata}`.
- **Loop variables** (`theme`, `gap`, `law`) — set by the enclosing `foreach`.
- **`upstream.lane_spec`** — when in a lane (`source.config.lane in (theme, gap)`), this is `source.config.theme` if lane==theme else `source.config.gap`. Holds `.laws[]` (the supporting_laws or related_laws list).
- **Convenience predicates**, all computed by **`bd list --status closed --json`** (NB: plain `bd list --json` excludes closed issues, so any predicate involving closed work needs the `--status` flag; for predicates that span both open and closed work, run both queries and union). Filters apply to task_type + status + config:
  - **`all_lane_syntheses_closed`** — every issue with `task_type=synthesis` and `config.run_kind=per_theme_gap_lane` under this epic is `status=closed`.
  - **`all_lane_analyses_closed`** — every `analysis` whose `config.lane == source.config.lane` is closed.
  - **`prior_synthesis`** — the closed `synthesis(run_kind=across_lanes)` if present, else the most recent closed per-lane synthesis.
  - **`all_lit_hypotheses_have_analyses`** — every `hypothesis(config.mode=literature_fanout)` has a closed `analysis` child (used by `hypothesis_driven_research`).
- **Lookup helpers** (compute on demand):
  - **`all_lane_syntheses`** — list of bd-ids of every closed per-lane synthesis.
  - **`all_lane_analyses`** — list of bd-ids of every closed analysis in the source's lane.
  - **`all_repro_analyses`** — same as all_lane_analyses (legacy alias).
  - **`all_lit_analyses`** — list of bd-ids of every closed analysis from the lit-fanout (hypothesis_driven_research only).
  - **`synthesis_across_lanes`** — bd-id of the unique closed `synthesis(run_kind=across_lanes)` issue.
  - **`latest_<task_type>`** — bd-id of the most-recently-closed task of that type in the epic, by `closed_at` (used by `iterative_theorizer` to reference the latest iteration of a step: `latest_literature_review`, `latest_extraction_schema_design`, `latest_theorizer_extraction`, `latest_theory_generation`, `latest_novelty_assessment`).
- **`user_feedback`** — set by `ask_user` when the picked option had a `followup_prompt:`; carries the user's free-text reply to that follow-up question. Unset (and a hard error to reference) outside that branch.

If a template references a name not in this list, the template is malformed — stop and surface the error.

## `${var}` interpolation

- Syntax: `${path.to.var}` — dotted attribute access only. No filters, no expressions.
- If `${var}` resolves to a JSON object or array, render it inline as JSON (e.g., `${theme.supporting_laws}` becomes `["node_2_3", "node_3_7", …]`).
- Unresolved placeholders are a hard error — stop and ask the user. Never persist a literal `${...}` to beads.
- Interpolation happens BEFORE `bd update --metadata`. Beads stores the fully-resolved strings.

## After either mode

Hand off to **update-summary** so `summary.md` reflects the new state.

## Out of scope

- Running tasks or producing outputs. That belongs to **execute**.
- Environment setup (installing `bd`/`jq`, `bd init`, `.asta/` skeleton). That belongs to **init**.
- Editing `mission.md` or selecting a template. That belongs to **brainstorm**.
- Validating output quality. (Structural validation happens in **execute** via `scripts/validate-output.sh`.)
