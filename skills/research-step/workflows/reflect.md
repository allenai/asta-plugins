# Workflow: reflect

Assess whether the just-closed task warrants reflection; if so, work through a
structured set of questions and write the result to `reflections/`. Always hands
off to **plan** or **update-summary** at the end.

## Preconditions

- A task was just closed by **execute**. The closed task's ID and `task_type`
  are in scope.

## Steps

1. **Decide whether to reflect.** Check the closed task's `task_type`:

   | task_type                                                                       | Action |
   |---------------------------------------------------------------------------------|---|
   | `literature_review`, `experiment_design`, `hypothesis`, `analysis`, `synthesis` | Continue to step 2. |
   | `scope`, `definitions`, `evidence_gathering`                                    | Skip to step 4. |

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

4. **Get researcher feedback.** Summarize your reflections. Point to the reflections file (md)
   for further details. Then display to the researcher the recommended next steps and allow
   the researcher to revise the steps as they see fit.

   Wait until the researcher is done deciding what should happen next.
   Once the researcher is satisfied with the next steps, continue to step 5.

5. **Label and confirm next steps.** Based on the confirmed next steps, restate them as a short list and label each as either:

   - **(in-plan)** — already represented in the current plan
   - **(new/changed)** — requires the plan to be updated
   - **(none)** — no further work proposed

   Show this labeled list to the researcher and ask them to confirm or correct the labels. The researcher may:

   - Accept the labels as-is.
   - Re-label an item (e.g., "that's actually already in the plan, mark it in-plan").
   - Revise the next steps themselves and re-label.

   Do not proceed to step 6 until the researcher confirms the labeled list.

6. **Hand off.**

   If the researcher explicitly directed a route during step 4 or 5 (e.g., "just update the summary," "go to plan"), honor that directive and skip the table.

   Otherwise, look at the labeled next steps confirmed in step 5 and route as follows:

   | Situation | Hand off to |
   |---|---|
   | Next steps add to, refine, or deviate from the current plan (new tasks needed, plan must be revised) | **plan** (with this task as the source) |
   | Next steps close out remaining open tasks and no further planning is needed right now (the current plan is effectively complete) | **update-summary** directly |
   | Next steps are empty / mission-level pause (researcher wants to stop, rescope, or revisit mission) | **update-summary**, then surface to researcher that mission may need revisiting |

## Out of scope for this workflow

- Mutating beads. The closed task was already closed by **execute**; this
  workflow is read-only with respect to beads.
- Structural output validation. That belongs to **execute**.
- Designing next tasks. That belongs to **plan**.
- Updating `summary.md`. That belongs to **update-summary**, which runs at the
  end of every chain.
