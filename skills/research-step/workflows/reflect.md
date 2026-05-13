# Workflow: reflect

Assess whether the just-closed task warrants reflection; if so, work through a
structured set of questions and write the result to `reflections/`. Always hands
off to **plan** or **update-summary** at the end.

## Preconditions

- A task was just closed by **execute**. The closed task's ID and `task_type`
  are in scope.

## Steps

1. **Decide whether to reflect.** Check the closed task's `task_type`:

   | task_type | Action |
   |---|---|
   | `literature_review`, `hypothesis`, `analysis`, `synthesis` | Continue to step 2. |
   | `scope`, `definitions`, `experiment_design`, `evidence_gathering` | Skip to step 4. |

2. **Load context.** Read `mission.md` for the exploratory dimensions. The
   closed task's output is already in scope from **execute** — do not re-fetch.

3. **Write the reflection.** Work through the following in order. This block is
   for the researcher to read; it is not filed into beads.

   **Summary** — one short paragraph: what was attempted and what was found.

   **Goal check** — what was this step trying to answer or resolve? Did the
   findings address that goal, partially address it, or miss it? Be direct.

   **Implications per exploratory dimension** — for each named dimension in
   `mission.md`, state what the findings mean concretely: what becomes more
   viable, what becomes less viable, what constraint is now visible that wasn't
   before.

   **Unresolved questions** — what questions did the findings raise that weren't
   there before? What was expected to be answered but wasn't? Be specific.

   **Decisions forced, deferred, or revised** — do these findings require a
   choice now? What are the options and tradeoffs? Do they suggest revising any
   past decision — which one and how?

   **Recommended next steps** — list the next possible research steps. Name
   contingencies and risks.

   Save to `reflections/YYYY-MM-DD-<bd-id>.md` (create the directory if it does
   not exist).

4. **Hand off.**

   | Closed task_type | Hand off to |
   |---|---|
   | `literature_review`, `hypothesis`, `analysis`, `synthesis` | **plan** (with this task as the source). |
   | `scope`, `definitions`, `experiment_design`, `evidence_gathering` | **update-summary** directly. |

## Out of scope for this workflow

- Mutating beads. The closed task was already closed by **execute**; this
  workflow is read-only with respect to beads.
- Structural output validation. That belongs to **execute**.
- Designing next tasks. That belongs to **plan**.
- Updating `summary.md`. That belongs to **update-summary**, which runs at the
  end of every chain.
