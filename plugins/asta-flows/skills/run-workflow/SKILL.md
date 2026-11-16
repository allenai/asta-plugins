---
name: run-workflow
description: Runs a research workflow with Theorizer, AutoDS, Semantic Scholar and Data Search. Use when someone brings a research question, papers, data or an AutoDS run and wants theories, hypotheses, experiments or a reproduction.
allowed-tools: Bash(theorize *) Bash(auto-discovery *) Bash(asta auth *) Bash(asta generate-theories *) Bash(asta autodiscovery *) Bash(s2 *) Bash(asta-papers *) Bash(jq *) Bash(uv tool *) Bash(uv venv *) Bash(uv pip *) Bash(command -v *) Bash(env *) Bash(grep *) Bash(echo *) Bash(cat *) Bash(curl *) Bash(python3 *) Bash(git *) Bash(quarto *) Bash(make *) Bash(mkdir *) Bash(ls *) Bash(cp *) Bash(ln *) Bash(touch *) Write Edit
---

# Asta Flows

## Workflows

| Workflow | What it does |
|---|---|
| [Theory generation](workflows/theory-generation/README.md) | Theories from the literature on a question, then a pass for each variable the first schema missed |
| [Data Driven Theory Generation](workflows/data-driven-theory-generation/README.md) | AutoDS experiments on real data, then theories that have to explain them |
| [Secondary reproduction](workflows/secondary-reproduction/README.md) | Re-tests an AutoDS run's hypotheses on independent data, then theories that explain the verdicts |
| [Gap-Driven Theory Testing](workflows/gap-driven-theory-testing/README.md) | Maps what the literature knows and leaves open, aims theories at the gaps, and tests them on independent data |
| [AutoDiscovery exploration](workflows/autodiscovery-exploration/README.md) | Breaks a researcher's question about their data into AutoDS runs, logs them, and writes up what came back |

Pick one with the person and read its README.

## Running Workflows

There are three ways to run workflows. Settle which one before anything else, once per project.

- **Library.** Use this if you want to do it in a coding agent: the agent does the reading and the analysis itself, using the Theorizer and AutoDS libraries' types. Subagents welcome.
- **CLI.** Use this if you have an API key and want to just use the command line, which bakes in our preferences.
- **Hosted.** We pay for it. Your data flows through our servers.

The library and the CLI run on this machine, and nothing goes to Asta.

To pick one, look first, without printing any key:

```bash
env | grep -oE '^(OPENAI|ANTHROPIC|MISTRAL|S2)_API_KEY'
echo "CLAUDECODE=${CLAUDECODE:-}"
asta auth status
cat .asta/mode.json
```

If that doesn't settle it, ask: "Is it okay for your data to leave this machine? If so, hosted is free. If not, I can use your API key with the CLI, or do it all here in this session with the library." In a hosted Asta sandbox, don't ask: use the CLI that's installed there.

Write the answer to `.asta/mode.json` (`{"mode": "library" | "cli" | "hosted"}`), and don't switch without asking. Each tool's skill has a file per mode: `generate-theories` for Theorizer and `autodiscovery` for AutoDS. Set up what the mode needs before you propose a workflow, and say what's missing if something won't install.

## Plan and run

Start from the person's mission, in their words. If their message states one, your first reply is the plan. If not, ask two or three targeted questions first (what they want to know, about what, and what for), then the plan.

The plan, and nothing more:

1. "Here's an example workflow:"
2. **Plan,** as the workflow's table, with the values for their question and the models from the tool's file for the mode. Add a flow chart if you can draw one.
3. **What they can change,** when the README lists it, word for word.
4. **One question,** on its own line: "Would you like to run the workflow, or provide an updated query?"

If they already asked for it to run on its own, write the plan to the run's `workflow.yaml` and go on. Don't fill in datasets, papers or hypotheses they left open; the run finds them. Run long commands in the background, and check each command's output before the next.

| What | Where |
|---|---|
| The run's files | `.asta/flows/<NNNN>-<workflow>/`: `workflow.yaml` (the plan), `README.md` (what ran, and where), and a folder per step, `<NN>-<step>/`, unless the workflow gives its own layout. Save each hosted result there as it finishes. |
| The run's page | `pages/<NNNN>-<workflow>.qmd`, front matter `title:` only: a heading per step and its widgets, nothing else |
| Datasets used | `.asta/datasets.json`: `[{id, name, released_by, used_for, links: [{label, url}]}]` |

In a hosted sandbox, a background job ends soon after your turn does. Wait for long steps inside the turn, tell the person every few minutes what's running, and if a job you expected is gone, say so and restart it.

## The front page

Every workflow ends with the front page, `index.qmd`. Its sections come from the workflow's own templates or `index.md` if it has them, and otherwise from the workspace's cover: Mission, Abstract, Findings, Null results, Next steps. Write it as a computational review ([write-up.md](write-up.md)), then run the `check-claims` skill over it and fix what it finds until it passes. Show the person the rendered page.

## Agents

| Agent | What it does | How |
|---|---|---|
| Semantic Scholar | Finds papers and follows references | `generate-theories`'s papers.md; the person's own documents can be added, or be the whole corpus |
| Data Search | Finds data a question can be tested on | Your own work with the web and a shell; describe what you find as `autodiscovery`'s "Describing the data" says |
| AutoDS | Searches over experiments on a dataset | the `autodiscovery` skill |
| Theorizer | Builds theories from papers | the `generate-theories` skill |
