---
name: plan-work
description: Write a detailed, executable plan for a single unit of work, then get it approved by review-plan. Updates work/<slug>/README.md with concrete instructions and sets status to ready (or needs-input if review repeatedly rejects).
allowed-tools: Read(work/**) Read(project.md) Edit(work/**) Write(work/**) Skill(asta-assistant:review-plan)
---

# Plan Work

Takes a vague goal in `work/<slug>/README.md` and produces a concrete, tool-aware plan that a downstream agent can execute without further design decisions.

## Inputs

- `work/<slug>/README.md` with at least the `Goal` section filled in. Frontmatter `status` is usually `pending-plan`.
- `project.md` for surrounding context (overall goal, background, related completed work).

## Output

Same `work/<slug>/README.md` with:

- `# Instructions` populated with a concrete plan (numbered steps; specific tools, commands, files, or skills to invoke; expected artifacts).
- Frontmatter `status: ready` (on approval) **or** `status: needs-input` (after repeated rejections).
- Frontmatter `plan_review_attempts: <int>` to track loops.

## Procedure

1. **Read context.** Open the work README and `project.md`. If the README's Goal section is empty or unclear, set `status: needs-input` and stop — do **not** invent a goal.

2. **Draft the plan.** Under `# Instructions`, write numbered steps that:
   - Name specific tools, commands, skills, or files for each step.
   - Identify expected outputs and where they land (e.g. `work/<slug>/data/<file>`).
   - Note any inputs from prior completed work (link the README).

3. **Update status and counter.**
   ```
   status: pending-review
   plan_review_attempts: <n+1>
   ```

4. **Invoke review-plan** with the slug. The review writes its verdict into the README (see review-plan).

5. **Read the verdict.**
   - If `status: ready` — done.
   - If `status: pending-plan` and the review left feedback in the README, incorporate it and loop to step 2.
   - After 3 failed review attempts, set `status: needs-input`, leave the latest review feedback in place, and stop. Surface to the user.

## Quality bar

A good plan is one a fresh agent could execute without asking design questions. Concretely:

- Each step says **what to do**, **which tool/skill**, and **what artifact it produces**.
- File paths are explicit, not "save somewhere appropriate".
- External calls (CLIs, APIs) include the exact subcommand.
- Order respects dependencies between steps.

## Out of scope

- Executing the plan (that is **do-work**).
- Deciding whether the goal itself is worth doing (that is **brainstorm**).
- Reviewing outcomes (that is **review-work**).
