---
name: run-workflow
description: Runs an Asta research workflow for the person, from plan to report, using Paper Finder, Data Search, AutoDS and Theorizer. Use when someone brings a research question, papers, data or an AutoDS run and wants theories, hypotheses, experiments or a reproduction.
allowed-tools: Bash(theorize *) Bash(auto-discovery *) Bash(uv tool *) Bash(command -v *)
---

# Research workflows

## Workflows

- [Theory generation](workflows/theory-generation.md): Theorizer plans a search query and schema, Paper Finder finds the papers, then Theorizer passes over the literature, one per extraction schema.
- [Data Driven Theory Generation](workflows/data-driven-theory-generation.md): Paper Finder, Data Search, AutoDS, then Theorizer to explain experimental findings.
- [Secondary reproduction](workflows/secondary-reproduction.md): re-test an AutoDS run's hypotheses on independent data, then build theories from the verdicts with Theorizer.

Pick one with the person and read its file.

## Setup

Check the environment before you propose a workflow: install what is missing and run `theorize doctor`. If a tool will not install or a key is missing, tell the person what is missing and what the run cannot do without it, before going further.

```bash
command -v theorize auto-discovery
uv tool install --upgrade "asta-theorizer>=0.1.4"
uv tool install --upgrade asta-autodiscovery
theorize doctor
```

Keys come from the environment. `theorize doctor` names every key the installed Theorizer reads, whether it is set, what a run loses without it, and how to set it, so follow it rather than a list here. AutoDS has no such check: it reads the key of its model's provider, such as `OPENAI_API_KEY` for `openai/` models.

## Plan and run

Your first reply is the plan, so the person can start the run with one answer. Ask nothing before it, unless their message has no question to run a workflow on. Propose it in this order, and nothing more:

1. "Here's an example workflow:"
2. **Plan,** as the workflow's table, with the values for their question. Mention the workspace only when the person gave files.
3. **What they can change,** when the workflow's file lists it, word for word as the file gives it.
4. **One question,** on its own line: "Would you like to run the workflow, or provide an updated query?"

Do not guess at datasets, papers or hypotheses in the plan, and do not fill in what the person left open, unless they ask you to choose. The run finds them.

Assume the person wants the workflow carried out autonomously unless they say otherwise. Keep the run's files in one directory. Run long commands in the background and check on them. Check each command's output before the next. Whether to hand a step to a subagent, and when, is your call.

## Agents

**Paper Finder** finds and fetches papers: `theorize papers search` searches with the plan's query, and `theorize papers fetch --top` fetches them in its order. `theorize papers import` adds the person's own documents: a folder (read recursively), a glob or files, of markdown, text or PDF. When the person says their papers are the corpus, add none.

**Data Search** finds the data a question can be tested on. There is no command for it; it is your own work with the web and a shell.

**AutoDS** runs a search over experiments on a dataset with `auto-discovery`: each experiment is a hypothesis, code, and how far its result moved belief.

**Theorizer** builds theories from the papers: `theorize plan`, `theorize extract` and `theorize theories generate`, then `theorize discover` and `theorize schemas from-discovery` for more schemas. [Theory generation](workflows/theory-generation.md) has the full sequence.

