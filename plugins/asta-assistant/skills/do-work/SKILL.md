---
name: do-work
description: Execute the approved plan in work/<slug>/README.md (status ready), write outputs into work/<slug>/data/, record what happened in the Results section, then hand off to review-work. Use when there is a ready work item.
allowed-tools: Read(work/**) Read(project.md) Edit(work/**) Write(work/**) Bash(*) Skill(asta-assistant:review-work) Skill(asta-tools:*) Skill(asta-preview:*)
---

# Do Work

Executes a single ready work item end-to-end. The plan in `# Instructions` is the contract; this skill follows it rather than redesigning it.

## Input

`work/<slug>/README.md` with `status: ready` and a populated `# Instructions` section.

## Output

- `work/<slug>/data/` — any data artifacts the plan produced. Each artifact should have a stable name referenced from the README.
- `work/<slug>/README.md` updated:
  - `# Results` populated with a natural-language narrative of what was actually done, what artifacts were produced, and anything that diverged from the plan.
  - Frontmatter `status: pending-assessment`.
- A handoff to **review-work** with the slug.

## Procedure

1. **Lock the item.** Set frontmatter `status: in-progress` to prevent re-entry.

2. **Read the plan.** Open `# Instructions`. If it is empty or vague, set `status: needs-input` and stop — the plan should have been concrete coming out of **plan-work**/**review-plan**. Do not improvise design decisions here.

3. **Execute step-by-step.** For each step:
   - Run the named tool/command/skill with the specified inputs.
   - Save artifacts under `work/<slug>/data/` using the names from the plan.
   - If a step fails, capture the error verbatim (do not silently retry with a different approach).

4. **Handle deviations.** When reality forces a deviation (a tool produced unexpected output, an external dependency is unavailable, a step turned out to be unnecessary), document it in `# Results` with: what was planned, what actually happened, why the deviation was justified. Do **not** silently substitute one step for another.

5. **Write `# Results`.** Structure:
   ```markdown
   # Results

   ## Summary
   <one paragraph>

   ## Artifacts
   - `data/<file>` — <one-line description>

   ## Step-by-step
   <what was done for each plan step, including deviations and failures>
   ```

6. **Set status and hand off.** Set frontmatter `status: pending-assessment`, then invoke **review-work** with the slug.

## Out of scope

- Designing or revising the plan (that is **plan-work**).
- Assessing success (that is **review-work**).
- Indexing or committing artifacts (that is **save-work**).
