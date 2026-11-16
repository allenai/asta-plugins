---
name: run-workflow
description: Runs an Asta research workflow for the person, from plan to report, using Semantic Scholar (`s2`), asta-papers, Data Search, AutoDS and Theorizer. Use when someone brings a research question, papers, data or an AutoDS run and wants theories, hypotheses, experiments or a reproduction.
allowed-tools: Bash(theorize *) Bash(auto-discovery *) Bash(s2 *) Bash(asta-papers *) Bash(jq *) Bash(uv tool *) Bash(command -v *)
---

# Research workflows

## Workflows

- [Theory generation](workflows/theory-generation/README.md): Theorizer plans a search query and schema, Semantic Scholar (`s2`) finds the papers and `asta-papers` fetches them, then Theorizer passes over the literature, one per extraction schema.
- [Data Driven Theory Generation](workflows/data-driven-theory-generation.md): Semantic Scholar, Data Search, AutoDS, then Theorizer to explain experimental findings.
- [Secondary reproduction](workflows/secondary-reproduction.md): re-test an AutoDS run's hypotheses on independent data, then build theories from the verdicts with Theorizer.
- [Gap-Driven Theory Testing](workflows/gap-driven-theory-testing.md): Semantic Scholar or a local paper index, a map of what the literature knows and leaves open, Theorizer theories aimed at the gaps, tests on independent data the person gives or Data Search finds, and the experiment each untested theory still needs.
- [AutoDiscovery exploration](workflows/autodiscovery-exploration/README.md): break a researcher's question about their data into AutoDS runs, log them, and write up what came back with every number linked to its experiment.
- [Computational review](workflows/computational-review.md): write the project's report, the site's front page, as a critical review of the evidence, with ComputationalReviewTemplate's Expert Review Pipeline and the `workspace` skill's citations and site.

Pick one with the person and read its file.

## Setup

Check the environment before you propose a workflow: install what is missing and run `theorize doctor`. If a tool will not install or a key is missing, tell the person what is missing and what the run cannot do without it, before going further.

```bash
command -v theorize auto-discovery
theorize --version   # already the version you want? skip its install line
uv tool install --upgrade --python 3.13 asta-theorizer --with "pymupdf4llm<2"
uv tool install --upgrade --python 3.13 asta-autodiscovery
theorize doctor
```

If `theorize` is already installed at the version the person or the environment asks for (for example, a newer build than PyPI's, provided for testing), keep it: `--upgrade` would replace it with PyPI's.

Both tools need `--python`: on the newest Python, a dependency they share has no prebuilt package and the install fails while compiling it. Each workflow's own setup section says what else its pins are for.

Keys come from the environment. `theorize doctor` names every key the installed Theorizer reads, whether it is set, what a run loses without it, and how to set it, so follow it rather than a list here. AutoDS has no such check: it reads the key of its model's provider, such as `ANTHROPIC_API_KEY` for `anthropic/` models.

## Plan and run

Start from the person's mission: what they want to find out or produce, in their words -- a question, a goal, a result to reproduce, or whatever it is. When their message states one, that is the mission: write it down as they put it, and your first reply is the plan, so they can start the run with one answer. When it does not, settle the mission first, the way a project's Goal is settled before work is planned: one message of two or three targeted questions (what they want to know or make, about what, and what it is for), then the plan. Do not interview them. Where the work is kept in a notebook, the mission heads its front page, and each run says how it serves the mission.

Propose the plan in this order, and nothing more:

1. "Here's an example workflow:"
2. **Plan,** as the workflow's table, with the values for their question. Mention the workspace only when the person gave files. If diagram tools are available, also make a flow chart of the plan and show it to the person.
3. **What they can change,** when the workflow's file lists it, word for word as the file gives it.
4. **One question,** on its own line: "Would you like to run the workflow, or provide an updated query?"

Do not guess at datasets, papers or hypotheses in the plan, and do not fill in what the person left open, unless they ask you to choose. The run finds them.

Assume the person wants the workflow carried out autonomously unless they say otherwise. Keep the run's files in one directory, laid out as [The run's files and page](#the-runs-files-and-page) says. Run long commands in the background and check on them (in a hosted sandbox, see [Long steps in a hosted sandbox](#long-steps-in-a-hosted-sandbox)). Check each command's output before the next. Whether to hand a step to a subagent, and when, is your call.

### The run's files and page

- **Files:** `.asta/flows/<NNNN>-<workflow>/`, numbered in the order the workspace's runs started, with a `workflow.yaml` (the plan: its steps and their settings), a `README.md` (what ran, and where each step's output is) and one folder per step, `<NN>-<step>/`.
- **Page,** in a workspace site: `pages/<NNNN>-<workflow>.qmd`, the same NNNN as the run's folder, its front matter only `title:`, normally the workflow's name. The sidebar lists the pages flat in run order, and they read one after another in that order.
- **Data the site reads:** what the steps write (the widgets' data files); `.asta/datasets.json` for the datasets the run used (`[{id, name, released_by, used_for, links: [{label, url}]}]`); and a gap run's theories written with `theorizer-site-data --gap <ID>`.

### Long steps in a hosted sandbox

Where you run in a hosted sandbox (the person reaches you through an app, not on their own machine), a background job ends soon after your turn does. So never end a turn with a job still running: wait for a long step inside the turn, checking on it, and tell the person every few minutes that it is still running and what it is on. If a turn starts and a job you expected is gone, say so plainly, restart it and wait for it in that turn; never send an empty reply.

## Agents

**Semantic Scholar and asta-papers** find and fetch papers: `s2` searches and follows references, `asta-papers store` fetches full text into a paper store, and `theorize papers import` brings the store into the project ([S2 to asta-papers to Theorizer](workflows/theory-generation/s2-papers.md)). Not `theorize papers search` or `theorize papers fetch`. `theorize papers import` adds the person's own documents: a folder (read recursively), a glob or files, of markdown, text or PDF. When the person says their papers are the corpus, add none.

**Data Search** finds the data a question can be tested on. There is no command for it; it is your own work with the web and a shell.

**AutoDS** runs a search over experiments on a dataset with `auto-discovery`: each experiment is a hypothesis, code, and how far its result moved belief.

**Theorizer** builds theories from the papers: `theorize plan`, `theorize extract` and `theorize theories generate`, then `theorize discover` and `theorize schemas from-discovery` for more schemas. [Theory generation](workflows/theory-generation/README.md) has the full sequence.

