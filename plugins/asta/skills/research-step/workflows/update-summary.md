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
3. **Gather state inline.**
   - `bd list --json --all --limit 0` for the full tree — `--all` because closed issues carry the results, `--limit 0` because bd truncates at 50 rows by default. Project to `{id, task_type: .metadata.research_step.task_type, title, status}` and partition by `.status`.
   - `scripts/next-task.sh` for the **next task and the queue** (open task-type issues, numerically sorted by id — the same order `execute` uses). This replaces `bd ready`; there are no edges, so id order is the ordering signal.
4. **Get the timestamp.** `generated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)`.
5. **Overwrite `summary.md`** using this template (sections come from the **new taxonomy** — flows, laws, theories, reports — not from any per-flow hardcoding; render what the closed tasks' `output_json` actually contains):

   ```markdown
   ---
   beads_snapshot: <hash>
   beads_epic: <bd-id>
   generated_at: <ISO-8601 UTC>
   issue_count: <n>
   open_task_count: <n>
   ---

   # <mission title>

   ## Mission
   <verbatim mission.md, or one-paragraph summary if long>

   ## Flow
   <one line per flow this session runs (from task metadata `flow`), with where it
   stands — e.g. "reproduction — replication branches 2/5 closed">>

   ## Results so far
   <one bullet per closed task: a one-line digest of its `output_json` —
   "<bd-id> [<task_type>]: <what it produced>" — e.g. laws grouped, datasets
   acquired, theories formed, verdicts finalized. When the session is complete, link
   to the rendered `report.pdf`.>

   ## Status
   - Closed: <n>
   - In progress: <n> — IDs: <list>
   - Open tasks: <n> — next: <`next:` from next-task.sh>; queue: <`queue:` line>

   ### Next Steps
   <the queue from next-task.sh in order, one bullet each:
   "- <bd-id> [<task_type>]: <title> — <one-line summary of the action this task will take>".
   If next-task.sh prints `next: none`, write "No open tasks — flow complete.">
   ```

6. **Render the session report when complete.** If `scripts/next-task.sh` prints `next: none` (no open tasks — the flow is done), run `scripts/compile-report.py --render` to deterministically render `report.qmd` → `report.pdf` from the closed tasks' typed outputs. This is the session deliverable; it is generated, not written. If `quarto` is unavailable, run `scripts/compile-report.py` (no `--render`) to still write `report.qmd`, and tell the user to install Quarto + tinytex to produce the PDF. Skip this step while open tasks remain.
7. **Report.** Print whether the file was rewritten and the snapshot hash. (The "already fresh" case exited at step 1.)

## Staleness check (for callers)

Any reader (human or agent) checks freshness by running `scripts/summary-check.sh`. Exit 0 ⇒ fresh; non-zero ⇒ run this workflow.

## Out of scope for this workflow

- Mutating beads. `update-summary` is read-only against `.beads/`.
- Re-planning. Even if no open tasks remain and the graph is incomplete, `update-summary` does not create issues.
