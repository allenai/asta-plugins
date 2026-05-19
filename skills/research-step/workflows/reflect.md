# Workflow: reflect

Assess whether the just-closed task warrants reflection; if so, work through a
structured set of questions and write the result to `reflections/`. Always hands
off to **plan** or **update-summary** at the end.

## Preconditions

- A task was just closed by **execute**. The closed task's ID and `task_type`
  are in scope.

## Steps

1. **Decide whether to reflect.** Check the closed task's `task_type`:

   | task_type                     | Action |
   |-------------------------------|---|
   | `scope', `evidence_gathering` | Skip to step 4. |
   | the rest                      | Continue to step 2. |
   
2. **Load context.** Read `mission.md` for the exploratory dimensions. The
   closed task's output is already in scope from **execute** — do not re-fetch.

3. **Write the reflection for researcher review.** Compose the reflection as a
   message *to the researcher* — they are the audience. Save it to the
   reflections file (md), then surface it in chat for review. This is not filed
   into beads.

   Work through the following sections in order:

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

   After writing, present to the researcher:
   - A brief (1-2 paragraph) summary of the reflection
   - A pointer to the reflections file for full details
   - The recommended next steps, displayed clearly for revision

   Then **iterate with the researcher on the next steps**. They may accept,
   reject, reorder, reshape, or replace any step. Treat each round of feedback
   as a revision: update the recommended next steps, show the revised list, and
   ask again. Do not proceed until the researcher explicitly confirms they are
   satisfied with the next steps.

   Once confirmed, continue to step 4.

4. **Label and confirm next steps.** Based on the confirmed next steps, restate them as a short list and label each as either:

   - **(in-plan)** — already represented in the current plan
   - **(new/changed)** — requires the plan to be updated
   - **(none)** — no further work proposed

   Show this labeled list to the researcher and ask them to confirm or correct the labels. The researcher may:

   - Accept the labels as-is.
   - Re-label an item (e.g., "that's actually already in the plan, mark it in-plan").
   - Revise the next steps themselves and re-label.

   Do not proceed to step 6 until the researcher confirms the labeled list.

5. **Hand off.**

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
