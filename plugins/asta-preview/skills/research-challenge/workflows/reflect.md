# Workflow: reflect

Interview the user about the project, then write a self-critical report at `RESEARCH_CHALLENGE.md` in the current working directory. The report covers what the project did, how Asta skills contributed, where the agent fell short, and how the skills could be improved.

This workflow is conversational. Do not write the report until the user has confirmed the summary and you have synthesized your own critique.

## Preconditions

None. Reflect runs from any state, including mid-project.

## Output file

`RESEARCH_CHALLENGE.md` in the current working directory. Use this exact name so **submit** can find it.

## Steps

### 1. Orient

Compute these signals once before the conversation:

- `PROJECT_DIR` = `pwd`
- Whether a prior `RESEARCH_CHALLENGE.md` already exists. If it does, read it; treat this run as a refinement, not a fresh start.

Skim the working directory (`ls`, `git log --oneline -20` if it's a repo) so you have concrete files and commits to reference. Do not deep-dive — you just need enough to ask informed questions.

### 2. Prompt the user for a project summary

Ask the user to describe the project. Useful prompts (pick the ones that fit; don't ask all of them):

- What was the research question or goal?
- What artifacts were produced (papers found, code written, datasets analyzed, hypotheses tested)?
- What's the headline result or current status?
- Which constraints or pivots shaped the work?

Keep this exchange short. One or two rounds is usually enough. Come up with a succinct project title and echo back a one-paragraph synthesis and get explicit confirmation before continuing.

### 3. Identify which Asta skills contributed

From your own conversation memory, list the Asta skills you actually invoked during this project (e.g. `find-literature`, `semantic-scholar`, `experiment`, `research-step`, `pdf-extraction`, etc.). For each, note in one sentence what it was used for and whether it produced a useful result.

If the project pre-dates this conversation, ask the user which skills were used rather than guessing.

### 4. Gather artifacts

Build the list of paths that will populate the `## Artifacts` section of the report. Include:

- `.beads/issues.jsonl` if it exists in `$PROJECT_DIR`. Do **not** include the rest of `.beads/` — the SQLite DB and other working state should not be submitted.
- Any files created or modified during this session (e.g. outputs from the **research-step** skill).
- `mission.md` if it exists, even if it pre-dates this session.

Use `git status` and `git log` (if `$PROJECT_DIR` is a repo) plus your own conversation memory to identify session-created files. If you are unsure whether a file belongs, ask the user rather than guessing. Resolve all paths relative to `$PROJECT_DIR`.

### 5. Self-critique

Without prompting from the user, write down — for your own use before drafting — a candid critique of your contribution. Cover at least:

- **Wrong turns.** Places where you misread the task, chased a dead end, or had to be corrected.
- **Friction.** Steps that took more turns than they should have, repeated tool failures, or context you should have surfaced earlier.
- **Gaps.** Things the user had to do themselves that you could plausibly have done, or analyses you skipped that would have strengthened the result.
- **What went well.** Don't omit this — it grounds the critique and informs the "keep doing" guidance.

Be specific. "I should have run `experiment` earlier" beats "I could have been faster."

### 6. Suggest skill modifications

For each skill you used, propose concrete changes that would have helped on this project. Examples of the form these should take:

- New steps or branches in a workflow.
- Better routing rules (when to invoke vs. when to skip).
- Missing defaults, env vars, or output conventions.
- New skills that should exist but don't.

Tie each suggestion to a moment in the project where it would have changed behavior. Vague suggestions ("make it smarter") are not useful — drop them.

### 7. Draft and write the report

Write `RESEARCH_CHALLENGE.md` with this structure:

```markdown
---
project: <slug>
date: <YYYY-MM-DD>
git_path: <absolute path>   # if $PROJECT_DIR is a git repo
working_dir: <absolute path> # otherwise
---

# <Project title>

## Summary

<2–4 paragraphs: question, approach, headline result, status. User-authored content from step 2, lightly edited.>

## Asta skills used

| Skill | Role on this project | Useful? |
|---|---|---|
| ... | ... | yes / partially / no |

## Self-critique

### What went well
- ...

### Where the agent fell short
- ...

## Suggested skill improvements

### <skill-name>
- **Observation:** <what happened in the project>
- **Suggested change:** <concrete change>

<repeat per skill / per suggestion>

## Artifacts

<Bulleted list of paths gathered in step 4. Used by the submit workflow to decide what to copy.>
```

Date is today's date. Slug is a short kebab-case name derived from the project title. Use `git_path` in the frontmatter when `$PROJECT_DIR` is inside a git repo (set it to the repo root); otherwise use `working_dir` with the absolute path.

### 8. Confirm and offer submit

Show the user the path you wrote to and offer to run the **submit** workflow. Do not chain automatically — submission is user-visible and opens a PR.

## Out of scope

- Editing other project files.
- Cloning or pushing to the asta-research-challenge repo. That is **submit**.
- Grading research quality on absolute merit. The critique is about *the agent's contribution*, not whether the science is correct.
