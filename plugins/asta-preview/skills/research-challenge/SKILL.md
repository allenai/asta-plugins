---
name: research-challenge
description: Summarize a research project conducted with Asta skills and submit it to the asta-research-challenge repository. Use when the user wants to reflect on a finished (or in-progress) project and/or share it with the Asta team. The user may say "reflect on this project", "submit my research challenge", or "write up what we did".
metadata:
  internal: true
allowed-tools: Bash(git:*) Bash(gh:*) Bash(pwd) Bash(date:*) Bash(ls:*) Bash(cp:*) Bash(mkdir:*) Bash(rm:*) Bash(find:*) Bash(du:*) Bash(wc:*) Bash(jq:*) Bash(sed:*) Bash(mktemp:*) Bash(scripts/*) Read(scripts/**) Read(workflows/**) Read(*) Write(*)
---

# Research Challenge

Capture what a research project in the current working directory accomplished, how the Asta skills contributed, and (optionally) submit the project as a contribution to https://github.com/allenai/asta-research-challenge.

This skill is a **router**. Pick the workflow that matches the user's intent, open its `.md` file in `workflows/`, and follow it. Do not execute a workflow from memory.

## Files

| Path | Role |
|---|---|
| `<cwd>/RESEARCH_CHALLENGE.md` | Output of **reflect**. Project summary, self-critique, and skill-improvement suggestions. Input to **submit**. |
| `~/.claude/projects/<encoded-cwd>/` | Source of conversation history transcripts (JSONL) — copied by **submit**. |

The `<encoded-cwd>` is the current working directory with `/` replaced by `-` (e.g. `/Users/x/work/proj` → `-Users-x-work-proj`).

## Workflows

| Name | Purpose | Detailed instructions |
|---|---|---|
| **reflect** | Interview the user about the project, self-critique the agent's contribution, suggest skill improvements, and write `RESEARCH_CHALLENGE.md`. | `workflows/reflect.md` |
| **submit** | Copy the report, conversation transcripts, and project artifacts into a new project-specific directory in a clone of `allenai/asta-research-challenge`, then open a PR. | `workflows/submit.md` |

## Routing

1. **Explicit request.** If the user names a workflow ("reflect on this", "write the report", "submit the challenge", "publish it"), dispatch directly.
2. **Implicit "wrap up" intent.** If the user is winding down a project but hasn't named a workflow, default to **reflect**, then offer **submit** at the end.
3. **Submit without a report.** If the user asks to submit but no `RESEARCH_CHALLENGE.md` exists, run **reflect** first and chain to **submit** on confirmation.

## Out of scope

- Grading research quality. The reflect workflow produces an honest self-critique, not a peer review.
- Pushing to `main` or merging the PR. **submit** opens a PR and stops.
