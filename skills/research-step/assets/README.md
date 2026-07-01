# Reading `workflows.yaml`

This skill defines and executes a research **workflow**: a sequence of **tasks**, each of
which produces a set of outputs with a defined **type**. Workflows, tasks, and types are
all declared in `workflows.yaml`. This doc is the reference for how to read that file;
the workflow `.md` files describe how to plan and execute against it.

## Key terms

| Term | What it is | In `workflows.yaml` |
|---|---|---|
| **type** | A record in the shared vocabulary (a law, an audit, a dataset, an artifact). The unit of data. | `types:` |
| **task** | A reusable **output contract**: the set of typed output keys one unit of work produces. A task is instantiated by a workflow step. | `tasks:` |
| **workflow** | A composition of tasks into a research process — an indented outline of steps and groups, plus `child_workflows` that compose other workflows. | `workflows:` |
| **vocabulary** | A closed value set referenced by type fields (e.g. `outcome`, `testability`). | `vocabulary:` |
| **config** | Session-tunable knobs and their defaults (e.g. `n_experiments`). | `config:` |

### Why `task` and `type` both exist

A **type** is a data shape; a **task** is the bundle of outputs a step emits. They are
separate because the same task is **reused across flows** — `analysis`, `audit`,
`data_acquisition`, and `experiment_design` each appear in three or more flows with the
same output contract but different inputs. Factoring the contract into `tasks:` keeps it
declared once; the flow step supplies the `input:` wiring. So `task` ≈ "a node's output
signature," not a second data type. (A task whose name matches a flow step is that step's
contract; a type whose name matches a task is a coincidence of naming.)

## Reading a flow

A flow is an indented outline, and the beads graph the **plan** workflow builds *is* that
same outline — each indentation level becomes one parent-child level, so hierarchical ids
(`wf`, `wf.1`, `wf.1.1`, …) encode position. There are **no dependency edges**; id order
is the ordering signal.

Reading a workflow node:

- A node with `cli_commands` is a **step** → a `task` issue tagged with its `task_type`. Its
  `cli_commands` are the asta commands it runs (`[]` for a reasoning-only step). Its `input:`
  names the upstream steps in this session whose issues are wired as the task's `inputs` (the
  same task takes different inputs in different workflows, so inputs live on the step, not the
  task). A `ref(<type>)` field holds a path to a record validated against `<type>`.
- A node with only child nodes and a `mission` is a **group** → a non-executable `epic` issue
  (a loop or a fan-out). The keys `mission`, `input`, `cli_commands`, `child_workflows`, and
  `replan` are never child nodes.
- A workflow's `child_workflows: [name, …]` composes other workflows in order: each named
  workflow is expanded in place (as a group) after the workflow's own children. Build the
  smaller workflows first; compositions reference them by name.
- A **fan-out group** inserts one branch level per item: the group node, then one branch
  epic per item, then the group's steps repeated under each branch. A group — or a composed
  workflow's root, e.g. `replication` — whose branches are created only at replan (one per
  law / hypothesis, once the naming step closes) declares `replan: true`.

## The output contract

- **Records are immutable.** A task emits a record once; later stages never re-emit it with
  new values. Verdicts and enrichments are their own records referencing the original by id
  (`audit_report.subject_id`, `source_access`/`acquisition` → `data_source_id`).
- **Agent payloads nest verbatim.** When a type carries another agent's record
  (experiment rows, `mcts_provenance`, or a referenced record like the `theory_components`
  file named by `theory.components_path`), the object is stored unmodified — inline under its
  key, or in the referenced file when it is too large for beads metadata. Top-level
  `output_json` keys are **closed**; nested objects stay **open**, so extra nested fields from
  real payloads are always permitted. A record stored by a `*_path` reference is still
  deep-validated against its type by `validate-output.sh`, so type safety survives going
  off-metadata.
- A field name ending in `?` (e.g. `mcts_provenance?`) is **optional**; unmarked fields are
  required. `[type]` means a JSON array of that type.
- `validate-output.sh` deep-validates `output_json` against the compiled per-task JSON
  Schema in `assets/compiled/` (regenerated from `workflows.yaml` by
  `scripts/compile-schemas.py` at build time).

## Artifacts vs. typed outputs

Every task carries an `artifacts` key holding **A2A 1.0 Artifacts** (camelCase wire fields):
each artifact is `{artifactId, name, description, parts, metadata}`, where `parts` is an
array of text / file / data parts. Conventions:

- Agents tag the artifact kind in `metadata.type` (e.g. `theory`, `theory_store`,
  `widget_data_voyager`, `extraction`; local byproducts use `figure`, `code`, `data`, `log`).
- Local files are **file parts in the uri form** — `uri` is a repo-root-relative path under
  `.asta/<agent>/<slug>/`, with a `mimeType`. Never the *bytes* form in `output_json`
  (beads caps metadata at ~64KB; base64 payloads are written to disk and referenced by uri).
- A value the contract *requires* (e.g. an analysis's figures) is a typed output key; an
  incidental byproduct travels the artifacts channel.
- **Citations / links.** `metadata` also wires the report's hyperlinks: `entity_id` names the
  law / theory / hypothesis / experiment the artifact backs (the report links that entity to
  this artifact), and `run_id` / `share_url` carry the producing run's Asta-UX deep link.
  `scripts/compile-report.py` links each entity to `share_url` when present, otherwise to the
  artifact's local file (relative, or absolute under `--base-url` for a published report).

## Where things live

- **beads metadata** (`metadata.research_step`): the typed `output_json` (slim, < ~64KB),
  the `flow`/`task_type`/`inputs` envelope, and the epic root's pinned `config`. This is the
  source of truth.
- **`.asta/<agent>/<slug>/`**: heavy artifacts (raw agent JSON, datasets, figures),
  referenced from `output_json` by repo-root-relative path. `<agent>` is the asta command
  group (`literature`, `generate-theories`, `autodiscovery`, `analyze-data`); `<slug>` is
  `YYYY-MM-DD-<short-query-slug>`.

## Outputs of a session

- **`output_json`** — the one thing the executing agent authors per task (typed, validated).
- **`report.pdf`** (and the site **`report.qmd`** body + **`report_anchors.json`** node↔section
  map) — the whole-session deliverable, **assembled** by `scripts/compile-report.py`: it reads the
  beads subtree, joins the primary records by id (laws⨝audits, theories⨝eval⨝triage⨝audit,
  hypotheses⨝audits, provenance, appendices), renders the paper-structured sections from the
  templates in `assets/templates/report/`, prepends a capability-labelled flow diagram, and renders
  to PDF via Quarto. There is no per-task narrative and no LLM-written report — the compiled report
  is the only human-facing view.

### Rendering (templates)

All human-facing wording lives in `assets/templates/report/`, not in Python. Each report section is
a `<section>.md.j2` Jinja template (`mission`, `abstract`, `methods`, `results_laws`,
`results_theories`, `results_hypotheses`, `trustworthiness`, `conclusions`, and the
`appendix_*` aggregates) whose headings carry stable `{#sec-…}` anchors and whose per-entity
subsections carry `{#ent-…}` anchors (these are what `report_anchors.json` maps graph nodes to).
`scripts/render.py` is the generic engine (no task-specific logic); `compile-report.py` supplies
each section's joined context.
