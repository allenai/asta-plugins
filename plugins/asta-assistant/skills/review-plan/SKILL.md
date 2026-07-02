---
name: review-plan
description: Critic skill. Given a plan in work/<slug>/README.md (status pending-review), check that the steps are concrete, the tools are appropriate, and the plan is realistic. Write a verdict and feedback back into the README.
allowed-tools: Read(work/**) Read(project.md) Edit(work/**)
---

# Review Plan

Independent review of a plan produced by **plan-work**. The reviewer reads only what is on disk; it does not see the planner's reasoning, by design.

## Input

`work/<slug>/README.md` with `status: pending-review` and a populated `# Instructions` section.

## Output

Same README, updated:

- On approval — frontmatter `status: ready`. Optionally append a short `# Review Notes` section summarizing why the plan was approved (one or two sentences).
- On rejection — frontmatter `status: pending-plan`. Append or overwrite a `# Review Feedback` section with specific, actionable issues for the planner to address.

## Checks

For each step in the plan, verify:

1. **Concreteness.** Does the step name a specific tool/skill/command, or is it hand-wavy ("analyze the data", "look up papers")? Hand-wavy steps are rejected.
2. **Tool fit.** Is the chosen tool/skill the right one for the job? Cross-reference available skills (e.g. `asta-tools:find-literature` for literature search, `asta-tools:experiment` for running experiments). Flag misuse.
3. **Dependencies.** Are inputs from prior steps/work referenced by path? Do later steps actually use earlier outputs?
4. **Artifacts.** Does each step that produces data say where the artifact lands (ideally `work/<slug>/data/...`)?
5. **Scope.** Does the plan actually accomplish the Goal? Or does it overshoot / undershoot?
6. **Realism.** Are runtimes, dependencies, and credentials plausible given the environment?

## Verdict rules

- Approve only if **all** six checks pass.
- Otherwise reject and write `# Review Feedback` listing the failed checks with one bullet per issue. Reference the specific step number.

## Out of scope

- Rewriting the plan. The reviewer only flags issues; **plan-work** revises.
- Assessing executed work. That is **review-work**.
- Modifying anything outside the work README.
