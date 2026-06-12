# Workflow: update-summary

Regenerate `summary.md` from beads. Idempotent and safe to run anytime. This is the only writer of `summary.md`. Beads remains the source of truth; `summary.md` is a derived view.

## Preconditions

- An epic root exists. Run `scripts/epic-root.sh` and read the `status:` line: `found` (with `id:` line) means an epic exists; `none` means no research session — abort with "no research session initialized — run `init` first".
- `bd` and `jq` are on PATH (used by `scripts/summary-check.sh`).

## Steps

1. **Check freshness.** Run `scripts/summary-check.sh`. It prints `status:` and (when applicable) `hash:` lines on stdout — read those directly:
   - **`status: fresh`** — `summary.md` is consistent with beads. **No-op.** Report "already fresh" and the snapshot hash; do not write.
   - **`status: missing`** or **`status: stale`** — file is missing or stale. Use the `hash:` line as the new `beads_snapshot`. Continue to step 2.
   - **`status: no-tools`** — `bd` or `jq` is not on PATH. Abort and tell the user to run `init` (which installs both).

2. **Locate the epic.** `epic_id=$(scripts/epic-root.sh | sed -n 's/^id: //p')`.
3. **Gather state inline.** Everything comes from `bd list --json`:
   - the full tree (issue_count, status partition);
   - the **open issues that have a `task_type`, sorted by id** — the first is the next task, the rest are the queue. This replaces `bd ready`; there are no edges, so id order is the ordering signal.
   Project to `{id, task_type: .metadata.research_step.task_type, title}` and partition by `.status`.
4. **Get the timestamp.** `generated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)`.
5. **Overwrite `summary.md`** using this template:

   ```markdown
   ---
   beads_snapshot: <hash>
   beads_epic: <bd-id>
   generated_at: <ISO-8601 UTC>
   issue_count: <n>
   ready_count: <n>
   ---

   # <mission title>

   ## Mission
   <verbatim mission.md, or one-paragraph summary if long>

   ## Research Question & Scope
   <from scope issue's output, or "pending" if not yet closed>

   ## Operational Definitions
   <from definitions issue's output>

   ## Related Work
   <literature_review.output.key_findings as bullets; link to summary_path>

   ## Hypotheses
   <one subsection per hypothesis issue: "H_n: <statement>" plus current verdict from its analysis if closed>

   ## Experimental Designs
   <one subsection per experiment_design, grouped under its hypothesis>

   ## Results Summary
   <table: hypothesis | verdict | confidence | analysis-id>

   ## Open Questions
   <synthesis.output.open_questions if synthesis exists, else aggregated from in-flight notes>

   ## Status
   - Closed: <n>
   - In progress: <n> — IDs: <list>
   - Open tasks: <n> — next: <smallest-id>; queue: <list of remaining open task ids>

   ### Next Steps
   <the open task-type issues sorted by id; lead with the next (smallest id), one bullet each:
   "- <bd-id> [<task_type>]: <title> — <one-line summary of the action this task will take>".
   If there are no open task issues, write "No open tasks — flow complete.">
   ```

6. **Report.** Print whether the file was rewritten and the snapshot hash. (The "already fresh" case exited at step 1.)

## Staleness check (for callers)

Any reader (human or agent) checks freshness by running `scripts/summary-check.sh`. Exit 0 ⇒ fresh; non-zero ⇒ run this workflow.

## Out of scope for this workflow

- Mutating beads. `update-summary` is read-only against `.beads/`.
- Re-planning. Even if no open tasks remain and the graph is incomplete, `update-summary` does not create issues.
