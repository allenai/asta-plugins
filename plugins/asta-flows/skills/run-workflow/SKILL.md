---
name: run-workflow
description: Runs a research workflow with Theorizer, AutoDS, Semantic Scholar and Data Search. Use when someone brings a research question, papers, data or an AutoDS run and wants theories, hypotheses, experiments or a reproduction.
allowed-tools: Bash(auto-discovery *) Bash(asta auth *) Bash(asta generate-theories *) Bash(asta autodiscovery *) Bash(s2 *) Bash(asta-papers *) Bash(jq *) Bash(uv tool *) Bash(uv venv *) Bash(uv pip *) Bash(command -v *) Bash(grep *) Bash(echo *) Bash(cat *) Bash(curl *) Bash(python3 *) Bash(git *) Bash(quarto *) Bash(make *) Bash(mkdir *) Bash(ls *) Bash(cp *) Bash(ln *) Bash(touch *) Write Edit
---

# Asta Flows

## Workflows

| Workflow | What it does |
|---|---|
| [Theory generation](workflows/theory-generation/README.md) | Theories from the literature on a question, then a pass for each variable the first schema missed |
| [Data Driven Theory Generation](workflows/data-driven-theory-generation/README.md) | AutoDS experiments on real data, then theories that have to explain them |
| [Secondary reproduction](workflows/secondary-reproduction/README.md) | Re-tests an AutoDS run's hypotheses on independent data, then theories that explain the verdicts |
| [Gap-Driven Theory Testing](workflows/gap-driven-theory-testing/README.md) | Maps what the literature knows and leaves open, aims theories at the gaps, and tests them with AutoDS on independent data |
| [AutoDiscovery exploration](workflows/autodiscovery-exploration/README.md) | Three ways to explore a dataset with AutoDS: on its own in rounds, theories first, or experiments first |

Pick one with the person and read its README. The default is Gap-Driven Theory Testing, with AutoDS running the tests; without data, its data step finds some. For a dataset to explore with no question, it's AutoDiscovery exploration.

Track every run in a workspace, with the `workspace` skill. Before starting a workflow, set up the workspace scaffold, start the local Quarto preview, and give the person its URL once it serves this project. The project's report, `index.qmd`, starts from [templates/report.qmd](templates/report.qmd), whatever the workflow, unless the person gives their own format: the mission in their words, the lead result they can act on, their questions and the answers, then the experiments, theories, findings, null results and next steps. A workflow's `templates/page.qmd`, when it has one, is the run's page.

After each workflow, update the report with what the run found. Cite each paper with its quote, name each theory, test, gap and AutoDS experiment ("Experiment N") a claim rests on, so the site links it to that item, and show the figures the findings rest on. Don't link files. Then run the `check-claims` skill on it and revise the report on what it finds: write, check, revise. Then render the site. When the workflow is done, give the person the site's URL and say what changed on it. Then ask the person how the run went, and submit their feedback to the Asta team with the `feedback` skill.

## Local or remote

Settle which before anything else, once per project.

- **Local.** On this computer, and nothing goes to Asta. With the person's API key, the tools run their own models; with none, you do the reading and the analysis yourself with the Theorizer and AutoDS libraries. Subagents welcome, two at a time unless the person says otherwise, each in its own folder.
- **Remote.** On Asta's servers. We pay for it, and the data goes there.

Ask which one they want, as part of the first conversation: "Would you like to run this locally or remotely? Remote is free, but your data leaves this computer. Locally, I use your API key, or with none I do the work here in this session." Don't look for keys or logins to decide for them. The person tells you how to reach their credentials: locally, ask where their key is (a key file, a variable in their shell, a password manager) and use only that; remotely, they log in with `asta auth login`. In an Asta sandbox, don't ask: run locally with what's installed there.

Write the answer to `.asta/mode.json` (`{"mode": "local" | "remote"}`), and don't switch without asking. Each tool's skill has `workflows/local.md` and `workflows/remote.md`: `generate-theories` for Theorizer and `autodiscovery` for AutoDS. Set up what the mode needs before you propose a workflow, and say what's missing if something won't install.

## Plan and run

Start from the person's mission, in their words. Once the mode is settled, if their message stated one, your next reply is the plan. If not, ask two or three targeted questions first (what they want to know, about what, and what for), then the plan.

The plan, and nothing more:

1. "Here's an example workflow:"
2. **Plan,** as the workflow's table, with the values for their question and the models from the tool's file for the mode. Add a flow chart if you can draw one.
3. **What they can change,** when the README lists it, word for word.
4. **One question,** on its own line: "Would you like to run the workflow, or provide an updated query?"

If they already asked for it to run on its own, write the plan to the run's `workflow.yaml` and go on. Don't fill in datasets, papers or hypotheses they left open; the run finds them. Run long commands in the background, and check each command's output before the next. In a hosted sandbox a background job ends soon after your turn does, so wait for long steps inside the turn and tell the person what's running.

Data Search has no command: it's your own work with the web and a shell. Describe what you find as the `autodiscovery` skill's "Describing the data" says.
