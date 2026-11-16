---
name: run-workflow
description: Runs an Asta research workflow for the person, from plan to front page, with Theorizer, AutoDS, Semantic Scholar and Data Search. Starts by settling how it runs -- the library in a coding agent, the CLI with your own key, or hosted by Asta. Use when someone brings a research question, papers, data or an AutoDS run and wants theories, hypotheses, experiments or a reproduction.
allowed-tools: Bash(theorize *) Bash(auto-discovery *) Bash(asta auth *) Bash(asta generate-theories *) Bash(asta autodiscovery *) Bash(s2 *) Bash(asta-papers *) Bash(jq *) Bash(uv tool *) Bash(uv venv *) Bash(uv pip *) Bash(command -v *) Bash(env *) Bash(grep *) Bash(echo *) Bash(cat *) Bash(curl *) Bash(python3 *) Bash(git *) Bash(quarto *) Bash(make *) Bash(mkdir *) Bash(ls *) Bash(cp *) Write(*) Edit(*)
---

# Research workflows

A workflow is a plan for using the tools together on a question. Each one is a folder: a README that says what it does and why, and sometimes an `index.md`, the front page it ends with. How to call each tool is in its own skill, not here.

## First: library, CLI or hosted

There are three ways to run this. Settle which one before anything else, once per project.

- **Library.** You pay for it. Use this if you just want to do it in a coding agent: the agent does the reading and the analysis itself, using the Theorizer and AutoDS libraries' types.
- **CLI.** You pay for it. Use this if you have an API key and want to just use the command line, which bakes in our preferences.
- **Hosted.** We pay for it. A great option if you're okay with your data going to our servers.

The library and the CLI run on this machine, and nothing goes to Asta. Your model provider still sees what it reads, as it does now.

To pick one, look first, without printing any key:

```bash
env | grep -oE '^(OPENAI|ANTHROPIC|MISTRAL|S2)_API_KEY'
echo "CLAUDECODE=${CLAUDECODE:-}"
asta auth status
cat .asta/mode.json
```

If that doesn't settle it, ask: "Is it okay for your data to leave this machine? If so, hosted is free. If not, I can use your API key with the CLI, or do it all here in this session with the library." In a hosted Asta sandbox the data is already with us, so don't ask: use the CLI that's installed there.

Write the answer to `.asta/mode.json` (`{"mode": "library" | "cli" | "hosted"}`) so you don't ask again, and don't switch without asking. Then use each tool's file for that mode: `generate-theories` for Theorizer and `autodiscovery` for AutoDS (both in asta-tools), each with a `library.md`, `cli.md` and `hosted.md`. Set up what the mode needs before you propose a workflow. If something won't install or a key is missing, say what's missing and what the run can't do without it.

## Workflows

- [Theory generation](workflows/theory-generation/README.md): theories from the literature on a question, then a pass for each variable the first schema missed.
- [Data Driven Theory Generation](workflows/data-driven-theory-generation/README.md): AutoDS experiments on real data, then theories that have to explain them.
- [Secondary reproduction](workflows/secondary-reproduction/README.md): re-test an AutoDS run's hypotheses on independent data, then theories that explain the verdicts.
- [Gap-Driven Theory Testing](workflows/gap-driven-theory-testing/README.md): map what the literature knows and leaves open, aim theories at the gaps, test them on independent data, and name the experiment each untested one still needs.
- [AutoDiscovery exploration](workflows/autodiscovery-exploration/README.md): AutoDS on someone's data in rounds of 50, each seeded with what surprised the last, with literature or theories alongside.

Pick one with the person and read its README.

## Plan and run

Start from the person's mission: what they want to find out or produce, in their words. When their message states one, that is the mission: write it down as they put it, and your first reply is the plan, so they can start the run with one answer. When it doesn't, settle it first with one message of two or three targeted questions (what they want to know or make, about what, and what it's for), then the plan. Don't interview them.

Propose the plan in this order, and nothing more:

1. "Here's an example workflow:"
2. **Plan,** as the workflow's table, with the values for their question, and the models from the tool's file for the mode. If diagram tools are available, also make a flow chart of the plan and show it.
3. **What they can change,** when the README lists it, word for word.
4. **One question,** on its own line: "Would you like to run the workflow, or provide an updated query?"

Don't guess at datasets, papers or hypotheses in the plan, and don't fill in what the person left open unless they ask you to choose. The run finds them.

Assume they want it carried out autonomously unless they say otherwise. Run long commands in the background and check on them. Check each command's output before the next. Whether to hand a step to a subagent is your call.

### The run's files and page

- **Files:** `.asta/flows/<NNNN>-<workflow>/`, numbered in the order the workspace's runs started, with a `workflow.yaml` (the plan: its steps and their settings), a `README.md` (what ran, and where each step's output is) and one folder per step, `<NN>-<step>/`. Save each hosted result there as soon as it finishes.
- **Page,** in a workspace site: `pages/<NNNN>-<workflow>.qmd`, its front matter only `title:`. It's widgets only: a heading per step and the widgets for that step's files. The sidebar lists the pages flat, in run order.
- **Data the site reads:** what the steps write; `.asta/datasets.json` for the datasets the run used (`[{id, name, released_by, used_for, links: [{label, url}]}]`); and a gap run's theories written with `theorizer-site-data --gap <ID>`.

## The front page

Every workflow ends the same way: the front page, `index.qmd`. Its sections are the workflow's `index.md` if it has one, and otherwise the workspace's cover: Mission, Abstract, Findings, Null results, Next steps. When a project runs more than one workflow, the front page covers all of them, in the latest one's sections.

Write it as a computational review, as [write-up.md](write-up.md) says. Then run the `check-claims` skill over it, fix what it finds, and run it again, until it passes. Show the person the rendered page before you call it done.

### Long steps in a hosted sandbox

Where you run in a hosted sandbox (the person reaches you through an app, not on their own machine), a background job ends soon after your turn does. So never end a turn with a job still running: wait for a long step inside the turn, checking on it, and tell the person every few minutes that it's still running and what it's on. If a turn starts and a job you expected is gone, say so plainly, restart it and wait for it in that turn; never send an empty reply.

## Agents

- **Semantic Scholar** finds papers and follows references (`generate-theories`'s papers.md, for the CLI). The person's own documents are added instead or as well; when they say their papers are the corpus, add none.
- **Data Search** finds the data a question can be tested on. There's no command for it: it's your own work with the web and a shell. Describe what you find as the `autodiscovery` skill's "Describing the data" says.
- **AutoDS** runs a search over experiments on a dataset: the `autodiscovery` skill.
- **Theorizer** builds theories from papers: the `generate-theories` skill.
