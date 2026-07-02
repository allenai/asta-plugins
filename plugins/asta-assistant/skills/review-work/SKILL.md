---
name: review-work
description: Critic skill. Given an executed work item (status pending-assessment), assess whether the Goal was actually accomplished. Identify the root cause when it was not (incorrect assumption, technical blocker, missing data). Updates work/<slug>/README.md Assessment section.
allowed-tools: Read(work/**) Read(project.md) Edit(work/**) Bash(ls work/**) Bash(jq *)
---

# Review Work

Independent assessment of executed work. Reads only what is on disk; it does not see the executor's reasoning, by design.

## Input

`work/<slug>/README.md` with `status: pending-assessment`, plus the artifacts under `work/<slug>/data/`.

## Output

Same README, updated:

- `# Assessment` populated with a verdict and explanation (see template below).
- Frontmatter `status: done` (if goal was accomplished) **or** `status: needs-input` (if it was not and human direction is needed) **or** `status: pending-plan` (if the assessment recommends a fresh plan attempt).

## Checks

1. **Goal vs Results.** Re-read the `# Goal` section. Compare against `# Results`. Does the work actually answer the goal, or only adjacent questions?
2. **Artifacts exist.** For every artifact named in `# Results`, verify it is present under `work/<slug>/data/`.
3. **Plan adherence.** Did execution follow the plan? Documented deviations are acceptable; undocumented substitution is a red flag.
4. **Evidence quality.** Are claims in `# Results` supported by the artifacts? Spot-check by reading a sample.

## Assessment template

```markdown
# Assessment

## Verdict
<accomplished | partial | not accomplished>

## Reasoning
<one or two paragraphs explaining the verdict against the Goal>

## Root cause (if not fully accomplished)
<one of: incorrect assumption | technical blocker | missing data | scope drift | other — with a sentence of detail>

## Recommended next status
<done | needs-input | pending-plan>
```

## Verdict rules

- `accomplished` → set `status: done`.
- `partial` with a clear next step the agent can take → set `status: pending-plan` and write a short note in the Assessment recommending what to plan next.
- `partial` or `not accomplished` requiring user input → set `status: needs-input`.

## Out of scope

- Re-running the work. That is **do-work**.
- Drafting a new plan. That is **plan-work**.
- Committing or indexing. That is **save-work**.
