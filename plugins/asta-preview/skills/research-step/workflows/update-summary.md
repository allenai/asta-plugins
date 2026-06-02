# Workflow: update-summary

Regenerate `summary.md` from beads + the per-task `output.json` files. Idempotent and safe to run anytime. This is the only writer of `summary.md`. Beads remains the source of truth; `summary.md` is a derived view.

## Preconditions

- An epic root exists. Run `scripts/epic-root.sh` and read the `status:` line: `found` (with `id:` line) means an epic exists; `none` means no research session — abort with "no research session initialized — run `init` first".
- `bd` and `jq` are on PATH (used by `scripts/summary-check.sh`).

## Steps

1. **Check freshness.** Run `scripts/summary-check.sh`. It prints `status:` and (when applicable) `hash:` lines on stdout — read those directly:
   - **`status: fresh`** — `summary.md` is consistent with beads. **No-op.** Report "already fresh" and the snapshot hash; do not write.
   - **`status: missing`** or **`status: stale`** — file is missing or stale. Use the `hash:` line as the new `beads_snapshot`. Continue to step 2.
   - **`status: no-tools`** — `bd` or `jq` is not on PATH. Abort and tell the user to run `init` (which installs both).

2. **Locate the epic and read its template.**
   ```
   epic_id=$(scripts/epic-root.sh | sed -n 's/^id: //p')
   template=$(bd show $epic_id --json | jq -r '.[0].metadata.research_step.template')
   ```

3. **Gather state inline.** All you need to fill the template comes from a few `bd` queries plus the per-task `output.json` files:
   - `bd list --json` for the full tree (issue counts, status partition, per-task metadata for joining).
   - `bd ready --json` for the ready list (also drives the Next Steps section).
   - `bd blocked --json` for the blocked count.
   - For each closed task, `cat .asta/tasks/<id>/output.json` to pull the structured fields needed in the digest (verdicts, themes, candidate_papers, etc.).

4. **Get the timestamp.** `generated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)`.

5. **Overwrite `summary.md`** using the template below. Sections marked *(template-conditional)* render only when the epic's template makes them meaningful.

   ```markdown
   ---
   beads_snapshot: <hash>
   beads_epic: <bd-id>
   template: <template_name>
   generated_at: <ISO-8601 UTC>
   issue_count: <n>
   ready_count: <n>
   ---

   # <mission title>

   ## Mission
   <verbatim mission.md body, or one-paragraph summary if long>

   ## Research Question & Scope
   <from scope task's output.json (question, boundaries, success_criteria), or "pending" if not yet closed>

   ## Operational Definitions
   <from definitions task's output.json (terms[])>

   ## Auto-Discovery Anchor  *(template-conditional: grounded_theory_generation only)*
   <from auto_discovery task's output.json:
    - run_id, metadata_path, nodes_path
    - laws table: | node_id | hypothesis (excerpt) | surprising | normalized_surprisal |>

   ## Related Work
   <from each literature_review task's output.json (key_findings, citations).
    In lane mode, group under the theme/gap name. Link to .asta/tasks/<id>/output.md.>

   ## Themes & Gaps  *(template-conditional: grounded_theory_generation only, after themes_and_gaps synthesis closes)*
   <from synthesis(run_kind=themes_and_gaps) output.json:
    - themes table: | name | description | supporting_laws |
    - gaps table:   | summary | why_open | related_laws |
    Each row links to the per-lane synthesis if one exists.>

   ## Hypotheses
   <one subsection per hypothesis issue. Renders the theory-shape: title + description +
    bulleted theory_statements. For mode==parametric_cross_cutting, render under a
    separate "Cross-cutting Theories" sub-section below.>

   ## Experimental Designs
   <one subsection per experiment_design, grouped under its lane or hypothesis>

   ## Results Summary
   <table: | hypothesis / law | verdict | confidence | bd-id of analysis | >

   ## Cross-cutting Theories  *(template-conditional: grounded_theory_generation only)*
   <from grounded_theory_generation task's output.json theories[]. For each:
    - name + description
    - bulleted theory_statements
    - negative_experiments (count)
    - novelty score if novelty_assessment has closed (per_statement[] verdicts)>

   ## Open Questions
   <synthesis output_json.open_questions[] if a synthesis is closed (use the latest
    run_kind in graph order: report > across_lanes > per_theme_gap_lane > lit_fanout > themes_and_gaps),
    else aggregated from in-flight notes.>

   ## Status
   - Closed: <n>
   - In progress: <n> — IDs: <list>
   - Ready: <n> — IDs: <list>
   - Blocked: <n>

   ### Next Steps
   <from `bd ready --json`: one bullet per ready issue, formatted as
   "- <bd-id> [<task_type>]: <title> — <input_instructions first sentence>".
   If `bd ready` is empty, write "No ready tasks — graph is blocked or complete.">
   ```

6. **Report.** Print whether the file was rewritten and the snapshot hash. (The "already fresh" case exited at step 1.)

## Backward compat for v1 sessions

If the epic's metadata is `output_schema_version: 1` (no `template:` field; closed tasks' outputs live in `metadata.research_step.output` rather than in `.asta/tasks/<id>/output.json`), fall back to the v1 render: read outputs from beads metadata, skip the template-conditional sections, omit the `template:` line in frontmatter. v2 sessions opt in by setting `output_schema_version: 2` on the epic.

## Staleness check (for callers)

Any reader (human or agent) checks freshness by running `scripts/summary-check.sh`. Exit 0 ⇒ fresh; non-zero ⇒ run this workflow.

## Out of scope for this workflow

- Mutating beads. `update-summary` is read-only against `.beads/`.
- Re-planning. Even if `bd ready` is empty and the graph is incomplete, `update-summary` does not create issues.
