---
name: autodiscovery
description: Runs AutoDiscovery (AutoDS) on a dataset -- hosted by Asta, with the `auto-discovery` CLI and your own key, or in the coding agent with the library -- and reads its experiments back. Use when someone wants to explore data with AutoDS, start, check or fork a run, or asks about their runs, experiments or discoveries.
allowed-tools: Bash(asta autodiscovery *) Bash(asta auth *) Bash(auto-discovery *) Bash(uv tool *) Bash(command -v *) Bash(grep *) Bash(python3 *) Bash(git *) Bash(mkdir *) Bash(ls *) Bash(nohup *) Bash(*/asta-autodiscovery/bin/python *) Bash(uv venv *) Bash(uv pip *) Bash(.venv/bin/*) Read Write Edit TaskOutput
---

# AutoDiscovery

AutoDiscovery (AutoDS) explores a dataset on its own. Each experiment is a hypothesis, a prior belief, code, its result and a posterior belief. How far the result moved the belief, its surprise, decides what it tries next. You give it the data, a description of the data and a prompt. It gives back a tree of experiments.

## Three ways to run it

- **Hosted.** We pay for it, in Asta credits. [hosted.md](hosted.md)
- **CLI.** You pay for it, with your own API key, on this computer. [cli.md](cli.md)
- **Library.** You pay for it, in a coding agent: the agent runs the experiments itself and saves them the way AutoDS does. [library.md](library.md)

If the project has settled this already (`.asta/mode.json`), use that. Otherwise ask, and don't switch partway through a run.

## Describing the data

AutoDS can only use what it's given, and it believes what you tell it.

- **From the data's own documentation:** what a row is, and for each column its meaning, units, coding and how missing values are written. Name the design: weights, clusters, strata, arms. Use the source's words. A column no source describes is undescribed; say so rather than guess. With no documentation at all, use the column names and what the person told you, say the meanings are inferred from them, and mark the rest undescribed.
- **Measured from the file:** the rows left after any restriction, and for each column how many values are present and its range or levels.
- **The cautions you can see in the bytes,** each with a number someone can check: sentinel values and unit traps, two columns that look alike but aren't the same thing, a quantity derived from another (so relating them is true by construction), rows that aren't independent, a group that dominates, a few extreme rows with a lot of leverage.
- **What the data are, never what they show.** No results, expected values, thresholds or hypotheses. A derived covariate is fine with its formula.
- **Give it more than the prompt needs.** It can only use the columns it gets. Keep the design variables, and include a second outcome measured the same way but with a different cause when there is one, so a result about the mechanism can be told from one about the measurement.
- **Data a script can't reach,** such as a portal behind an account or a data-use agreement: if the person is there, open the page in the browser or with computer use, and let them sign in and download it with their own credentials. Then describe the file they saved. Never type their password yourself.
- **Keep restricted row-level data out of git.** Commit the script that builds the extract, and each file's row count and hash.

## The prompt

- **Say where to look, as the person would put it:** the question or the area, and a contrast if they asked for one. Don't list columns; choosing them is the search.
- **Never say what to find:** no mechanism, direction, effect size or earlier result, in the prompt or the description. AutoDS told what to find tends to find it. Grep both for words like `associated`, `higher`, `lower`, `more likely`, `increase`, `decrease`, `effect`, `odds`, `expected`, `predicts`, then read them once more, since a grep catches wording, not intent.
- **Keep it narrow.** 50 experiments only go a few deep on each thing they're asked about.
- **No question?** Then the prompt is "Explore the data".

## The loop

AutoDS works as a loop. Start with 50 experiments: about one dollar hosted (50 credits). With your own key, cli.md has the cost per model.

Then look at the experiments AutoDS flagged as surprising, in this order:

1. **False to true:** belief started at or below 0.5 and ended above it. These matter most.
2. **True to true:** above 0.5 before and after, and it went up.
3. **True to false:** above 0.5 before, below after.

Read each one before you use it, because a bug or a leak also flips a belief. Seed the next 50 with the top three to five (fewer if fewer are surprising), and go again. Stop when a round brings no new surprising shift, or when the person's budget runs out if they set one. Check in with the person after each round, unless they've said to keep going.

To seed a round, its prompt drills into the picks: "Explore further: <what each pick was about>". Name what they looked at, not what they found, and run the same grep on the new prompt. On the CLI you can also hand it the picks themselves (cli.md). In the library, keep adding nodes to the same folder.

## Reading the results

- **What's in an experiment:** the hypothesis, the plan, the code and its output, AutoDS's analysis, the prior and posterior beliefs, the surprise, and whether it counts as surprising.
- **Read every experiment before you trust any.** For each large belief change, ask what caused it. A bug, a leak or a quantity that's true by construction moves belief a lot and means nothing: mark it as an artifact. A result that confirms the prior is real, just not surprising.
- **Count the surprising ones yourself,** from each experiment's flag. A hosted run's `stats.num_surprising_experiments` has read 0 with three flagged.
- **If the beliefs barely vary** (they sit on a coarse grid and can collapse to two or three values), the surprising flags and the ranks are mostly ties. Say so.
- **Group the repeats.** AutoDS often tests one finding several times in different words; report it once, with every experiment that found it. Flag a cutoff or subgroup an experiment chose after looking at the data: it overstates the result.
- **Say why the search stopped,** and how many experiments ran and failed. A partial run, called partial, is still usable.
- **When you show someone a run,** give the counts, a few of the most surprising experiments in their own words (hypothesis and analysis), and offer to go deeper. Show code only if asked.

## The run's files

| Mode | What you save | Each experiment's fields |
|---|---|---|
| Hosted | `asta autodiscovery results <runid> -o results.json` | `hypothesis`, `experiment_plan`, `code`, `code_output`, `analysis`, `review`, `prior`, `posterior` (means), `surprise` (signed), `is_surprising`, `id_in_run`, `experiment_id`, `parent_id` |
| CLI, library | the run's `mcts_node_*.json` | `hypothesis`, `experiment_plan`, `code`, `code_output`, `analysis`, `review`, `success`, `prior.mean`, `posterior.mean`, `belief_change` (unsigned), `normalized_surprisal` (signed), `surprising`, `creation_idx`, `id`, `parent_id` |

`experiment_plan` is an object (`objective`, `steps`, `deliverables`). A hosted `results.json` can run to tens of megabytes; keep it out of git.

- In CLI and library runs, `node_1_0` only loads the data: it has no hypothesis or beliefs, so skip it when you rank. Hosted results leave it out.
- For a direction, use posterior minus prior (hosted `surprise` is already signed), not `belief_change`.
- Experiment N is the node with `creation_idx` N + 1 in every mode (hosted: `id_in_run` N).
- The workspace's `asta-autods` widget draws either kind, from the files on disk: download a hosted run's `results.json` into the run's folder and point the widget at it, so every experiment and its plots work offline.
