---
name: feedback
description: Interview the user about their experience with the Asta plugins and tools, write a narrative feedback report, and submit it (with optional supporting files) to the Asta team for analysis. Use when the user wants to "give feedback", "send feedback to the Asta team", "report how this went", or "tell Ai2 what I think".
allowed-tools: Bash(asta feedback:*) Bash(asta auth:*) Bash(pwd) Bash(date:*) Bash(ls:*) Bash(cp:*) Bash(mkdir:*) Bash(find:*) Bash(du:*) Bash(wc:*) Read(*) Write(*) Edit(*)
---

# Feedback

Help a user tell the Asta team how using these plugins actually went. The skill interviews the user, synthesizes a **narrative report** (`FEEDBACK.md`), optionally gathers a few agent-generated reports that illustrate the story, and submits the bundle, via `asta feedback submit`, to a private store the Asta team analyzes.

This is meant to be low-friction for the user, with ability to review the information being submitted.
Place feedback into a `<project-root>/.asta/feedback/<slug>/` directory, where `<slug>` is a short, dated kebab-case name (e.g. `2026-07-30-glaciar-evolution-analysis`)

This skill is a **router**. Pick the workflow that matches the user's intent, open its `.md` file in `workflows/`, and follow it. Do not execute a workflow from memory.

## Workflows

| Name | Purpose | Detailed instructions |
|---|---|---|
| **interview** | Converse with the user about their experience, then write `FEEDBACK.md` and stage any supporting files into a submission directory. | `workflows/interview.md` |
| **submit** | Let the user review the submission directory, then run `asta feedback submit <dir>` to upload it. | `workflows/submit.md` |

## Routing

1. **Explicit request.** If the user names a phase ("write up my feedback", "submit the feedback"), dispatch directly.
2. **General "give feedback" intent.** Default to **interview**, then offer **submit** at the end. Do not chain automatically — submission is user-visible.
3. **Submit without a report.** If the user asks to submit but no `FEEDBACK.md` exists, run **interview** first and chain to **submit** on confirmation.

## Related skills for Asta team members

Asta team members may use this skill to comment on the *experience of using the tools*. 
To self-reflect on a research project or update the skill benchmarks, use `research-challenge` or `improve-skills` from the `asta-dev` plugin. 

## Out of scope

- Uploading datasets or large working files. Supporting files are small agent-generated reports that illustrate the narrative, not inputs of independent interest — the CLI enforces size gates.
- Grading research quality.
