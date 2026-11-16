---
name: run-workflow
description: Runs an Asta research workflow for the person, from plan to report, with Theorizer, AutoDS, Semantic Scholar and Data Search. Starts by settling how it runs -- the library in a coding agent, the CLI with your own key, or hosted by Asta. Use when someone brings a research question, papers, data or an AutoDS run and wants theories, hypotheses, experiments or a reproduction.
allowed-tools: Bash(theorize *) Bash(auto-discovery *) Bash(asta auth *) Bash(asta generate-theories *) Bash(asta autodiscovery *) Bash(s2 *) Bash(asta-papers *) Bash(jq *) Bash(uv tool *) Bash(command -v *)
---

# Research workflows

## First: library, CLI or hosted

There are three ways to run this. Settle which one before anything else, once per project.

- **Library.** You pay for it. Use this if you just want to do it in a coding agent: the agent does the reading and the analysis itself, using the Theorizer and AutoDS libraries' types. [library.md](modes/library.md)
- **CLI.** You pay for it. Use this if you have an API key and want to just use the command line, which bakes in our preferences. [cli.md](modes/cli.md)
- **Hosted.** We pay for it. A great option if you're okay with your data going to our servers. [hosted.md](modes/hosted.md)

The library and the CLI run on this machine, and nothing goes to Asta. Your model provider still sees what it reads, as it does now.

To pick one, look first, without printing any key:

```bash
env | grep -oE '^(OPENAI|ANTHROPIC|MISTRAL|S2)_API_KEY'; echo "CLAUDECODE=${CLAUDECODE:-}"
asta auth status 2>/dev/null; cat .asta/mode.json 2>/dev/null
```

If that doesn't settle it, ask: "Is it okay for your data to leave this machine? If so, hosted is free. If not, I can use your API key with the CLI, or do it all here in this session with the library." In a hosted Asta sandbox the data is already with us, so don't ask: use the CLI that's installed there.

Write the answer to `.asta/mode.json` (`{"mode": "library" | "cli" | "hosted"}`) so you don't ask again, and don't switch without asking.

## Workflows

- [Theory generation](workflows/theory-generation/README.md): plan a search query and extraction schema, find and fetch the papers, extract findings, generate theories, then a pass per new schema.
- [Data Driven Theory Generation](workflows/data-driven-theory-generation.md): Semantic Scholar, Data Search, AutoDS, then Theorizer to explain experimental findings.
- [Secondary reproduction](workflows/secondary-reproduction.md): re-test an AutoDS run's hypotheses on independent data, then build theories from the verdicts with Theorizer.
- [Gap-Driven Theory Testing](workflows/gap-driven-theory-testing.md): a map of what the literature knows and leaves open, Theorizer theories aimed at the gaps, tests on independent data the person gives or Data Search finds, and the experiment each untested theory still needs.
- [AutoDiscovery exploration](workflows/autodiscovery-exploration/README.md): break a researcher's question about their data into AutoDS runs, log them, and write up what came back with every number linked to its experiment.
- [Computational review](workflows/computational-review.md): write the project's report, the site's front page, as a critical review of the evidence, with ComputationalReviewTemplate's Expert Review Pipeline and the `workspace` skill's citations and site.

Pick one with the person and read its file. The workflow files give their steps as CLI commands (`theorize …`, `auto-discovery …`). For the library or hosted, the mode's file says what to use instead. Everything else stays the same.

## Setup

Set up what the mode needs, from its file, before you propose a workflow. If a tool will not install or a key is missing, tell the person what is missing and what the run cannot do without it, before going further.

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

What each one does is the same in every mode. How you run it is in the mode's file.

**Semantic Scholar** finds papers and follows references. The person's own documents (a folder, a glob or files, of markdown, text or PDF) are added instead or as well; when they say their papers are the corpus, add none.

**Data Search** finds the data a question can be tested on. There is no command for it; it is your own work with the web and a shell.

**AutoDS** runs a search over experiments on a dataset: each experiment is a hypothesis, a prior belief, code, its result and a posterior belief, and how far the result moved belief (its surprise) decides what to try next.

**Theorizer** builds theories from the papers: plan a query and extraction schema, extract findings per paper, generate theories whose laws cite those findings, then discover the variables the schema missed. [Theory generation](workflows/theory-generation/README.md) has the full sequence.
