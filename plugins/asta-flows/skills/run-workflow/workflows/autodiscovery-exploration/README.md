# AutoDiscovery exploration

A team nominates a dataset they already work with and writes down its mission: what they want to learn, and what it would change. AutoDiscovery searches the data and returns a ranked list of surfaced hypotheses. The team reviews the list together, decides what is worth following up or validating, and starts more runs from those decisions. Before the review, the agent passes over every experiment and drafts the write-up for the team to review from; keeping and publishing it afterwards, with null results, is optional. The workflow leaves the record the collaboration asks for in one version-controlled repository: the mission, the extraction script, and each run's configuration and experiments.

The researcher's part is the mission, settling the runs, and the review. The workflow stops before any run is created, at the review, and before anything is published. Budget an hour or two of their time.

## Setup

```bash
asta auth login                 # once; the runs use the hosted service
asta autodiscovery credits      # the balance has to cover the budget
```

The project is an Asta workspace (the `workspace` skill): a git repository that renders to a site, one mission per repository. The repository is the team's, in their own organisation and private when the data terms say so; nothing in the workflow depends on where it lives. The site is published where the team publishes, a public unlisted site, a private one, or not at all: the rendered site is a folder of HTML that can be shared by hand.

Data stays where it belongs. AutoDiscovery sees an extract, and the source data and the extract never enter git. When the extract may not be uploaded to the hosted service, the team brings its own keys: the autodiscovery skill's local workflow runs the `asta-autodiscovery` CLI on their machine against the model their key points at, with no credits. Say once that this model receives the data descriptions, the generated code and its printed output, as with any use of that key, and leave the choice of model to the team; it is theirs to make under their own data terms, so do not propose other providers or a smaller extract unless asked. The record is the same: point the CLI's `--out_dir` at `.asta/autodiscovery/<run>/local/`, and `runlog.py` reads it as it reads a hosted run. A local run's `run.md` has no link.

## Plan

Show the person this table with the values for their dataset. Anything not in it runs on the service's defaults.

| Name | Description | Configuration |
|---|---|---|
| Nominate the dataset | Set up the repository and look at the data | the repository the person names |
| Define the mission | Draft `mission.md` with the person: the goal, the data, the constraints | |
| Plan the runs | One run by default, more only for angles the person names; the prompts, the budget and the extract | one run of 50 experiments; as much of the data as can be extracted |
| Extract and describe | Build the extract and describe it for AutoDiscovery | |
| Run AutoDiscovery | Run, then save each run's record and its experiments table | |
| Draft for review | A pass over every experiment, and the write-up drafted from it | |
| Review together | The team's decisions on the experiments | |
| Write up | Optional: the draft rewritten from the decisions, then published | |

After the table, list what they can change:

> - **Budget:** 50 experiments by default (credits on the hosted service; model cost with your own keys).
> - **Runs:** add a run for a different angle, such as a different outcome or a different file.
> - **Data:** as much of the data as can be extracted, by default; name what to leave out to narrow it.

The workflow is collaborative. Even when the person asks for it to run on its own, the mission, the settling of the runs and the review are theirs.

## Steps

1. **Nominate the dataset.** Scaffold the repository with the `workspace` skill, then copy this folder's `templates/` over it (the site config, the write-up, `mission.md`, the README and the ignore rules) and its `scripts/` into `scripts/`. Then look at the data: what the files or tables hold, how the data were collected (weights, clusters, strata, arms), and what the mission would need that is not there. Keep notes in the repository if they help; they are not a page.

2. **Define the mission.** Draft `mission.md` with the person: what they want to learn and what it would change, in their words, with their message quoted as sent; the data; what is not available; and the constraints, such as the data terms. It does not have to be a question. With nothing more specific, the mission is to see what the data hold.

3. **Plan the runs.** One run of 50 experiments on the main file, with the person's prompt ([Seeding protocol](#seeding-protocol)). Add a run only when the person names a different angle, such as a different outcome, population or file; do not split their prompt into sub-questions. A run of fifty experiments goes only a few deep on each thing it asks about, so a prompt that asks for a great deal spreads thin; say so once if it does. For each run, write `runs/<run>/run.md` ([The run folder](#the-run-folder)), and list the extract: by default as much of the data as can be extracted, whatever the prompt names (step 4). Note, in a few lines, data not in the source that would change the plan, such as a record the researcher may hold.

   Then show the mission, the runs with their prompts and experiment counts, the budget, the extract, and the data that would change the plan. Ask what they would change. End with one question on its own line, such as "Create these runs, or change them?", and do nothing further until they answer.

4. **Extract and describe.** Write the extraction in whatever the team works in, Python, R, Stata, SQL or a notebook, and commit it, so the extract can be rebuilt. Record each file's row count and a hash in `mission.md`.

   Extract as much of the data as you can, unless the person asks to narrow it: every variable that can be joined to the row unit and described, from every file in the source, not only the ones the prompt or the mission names. AutoDiscovery can only use the columns it is given, and the unexpected results come from the columns nobody asked about. Leave out only what the data terms or the person exclude, direct identifiers, and what cannot be described; say what was left out and why in `mission.md`. If the service's limits on file size or description length would be exceeded, say so and ask what to drop rather than choosing. Keep the design variables, and include a second outcome that is measured the same way but has a different cause when the source has one; it lets a reader tell a result about the mechanism from one about the measurement.

   Describe each file for AutoDiscovery in its run's `run.md`: what a row is, each column's meaning, units, coding and missingness, the design, technical cautions. Say what the data are, not what they show. No thresholds, definitions or derived outcomes that belong to the mission; derived covariates are fine with their formula. Run the neutrality check over every prompt and description.

5. **Run AutoDiscovery.** For each run: `asta autodiscovery create`, `upload` the files, `metadata` from a JSON file made from its `run.md` (`name`, `domain`, `description`, the prompt as `intent`, `datasets` with each file's name and description, and `experiments` as `n_experiments`; keep it as `.asta/autodiscovery/<run>/metadata.json`), `metadata-get` to confirm name, prompt, files and experiment count match, then `submit`. A run of 50 takes about two hours. Poll until it finishes, then save its full record as `.asta/autodiscovery/<run>/results.json` (`asta autodiscovery results`), following the `.asta/<skill>/` convention for skill outputs. Share the run in the AutoDiscovery app, put its shared link in `run.md`, and open one experiment link in a private window to confirm it needs no sign-in. Then `python3 scripts/runlog.py` writes the run's `experiments.csv` and its figures; it stops if any experiment text looks like row-level data. Commit the run folder, the record and the figures.

6. **Draft for review.** Unless the team asks to review the experiments alone, pass over every experiment and draft the write-up ([The draft](#the-draft)). Render it with `make check`, then look at the served page itself: a page whose placeholders or front matter fail can pass the check and render empty. Show the researcher the local preview; do not publish the draft.

7. **Review together.** Stop. The review is the team's ([Review together](#review-together)).

8. **More runs.** New runs start from the review's decisions: back to step 3, in the same repository, as a pull request whose description says why. `asta autodiscovery fork <run id>` starts a run with another run's metadata and files, to change only the prompt. Change `mission.md` only when the goal changes. Data that arrives later gets a new extract with its own hash.

9. **Write up.** Only when the team wants the write-up kept ([The write-up](#the-write-up)). Rewrite the draft from the review: experiments marked `Flawed` leave Findings, or move to Null results with the team's notes; Next steps lists what was marked `Follow up` or `Validate`. Remove the draft callout and the **What to check** lines, keeping any caution the review confirmed in the sentence on how far to trust a finding. Run the `check-claims` skill over it, confirm each quote is verbatim in its run's `experiments.csv`, render with `make check`, show the researcher the preview, and publish once they have seen it.

## Seeding protocol

A seed prompt says where to look, in plain language, in the person's words: the mission, or the angle the run takes. It does not need to list columns; the description already tells AutoDiscovery what the data hold, and choosing columns is the search. It does not name a mechanism, a direction, an effect size or an earlier result, and neither does the description: AutoDiscovery told what to find tends to find it. With no prompt, the prompt is one line: explore the data; there is no specific question.

One sentence on what the measurement can and cannot show may be added to every prompt, the same on each.

Before anything is created, search every prompt and description for direction and result words (`associated`, `higher`, `lower`, `more likely`, `less likely`, `increase`, `decrease`, `effect`, `odds`, `expected`, `predicts`, `known findings`), and for terms that would name a result in this project. A grep is enough; it catches wording, not intent, so read the prompts once more. Show the person what it finds rather than rewriting their words.

## The run folder

`runs/<run>/run.md` is the configuration the run was submitted with, the same fields as the AutoDiscovery web app's form:

```markdown
---
name: "<the run's name in AutoDiscovery>"
experiments: 50
files: [<file>.csv]
link: <the run's shared link, once shared>
---

## Prompt

<the prompt>

## Description

<the run's description>

## <file>.csv

<the file's description>
```

Quote `name` and `title`: a colon in a run's name breaks the front matter. Optional fields: `title` (a short title for the run), `label` (the letter in the write-up's markers, such as A for A-32), `domain`, and any search setting changed from the service's default.

`runs/<run>/experiments.csv` is one row per experiment: `ID`, then two columns left empty for the review, `Next step` and `Review notes`, then the rest of the web app's download of a run in its order (`Hypothesis` to `Deliverables`). A team using the web app saves the download here and adds the two review columns after `ID`. `runlog.py` writes it once the run has finished, and leaves it alone after that.

## The draft

The pass reads each experiment in full from the run's record (its plan, code and printed output), not only its row in `experiments.csv`, and looks for what would make a result not stand: a sample selected on the outcome or on something it causes, a variable that leaks the outcome, the survey design ignored where it matters, the wrong test or unit, many comparisons read as one, too few cases, an explanation that goes further than the numbers, an ID used twice. It does not fill `Next step` or `Review notes`; those are the team's.

The draft is the write-up ([The write-up](#the-write-up)) with three differences. The template's draft callout stays at the top and lists the experiments to check first, each with its ID and a line on why. Each finding ends with a **What to check** line: the concern from the pass, or what a reviewer would need to confirm, such as an explanation the numbers alone cannot carry. A striking result with a flaw stays in, with the flaw stated; the review decides. Next steps is left for the review.

## Review together

The researcher and the team go through each run's `experiments.csv`, with the draft open beside it, and decide, as a team, what to do with each experiment. `Next step` is `Follow up` (worth another analysis), `Validate` (worth a small check against other data or a rerun), `No action`, or `Flawed` (the experiment itself does not stand); blank means not yet reviewed. `Review notes` says why: what makes the result convincing, or what is wrong with the method (the wrong test, a bad assumption, a variable that leaks the outcome). A team can add any other columns that help its review. The decisions are committed and are what the next runs start from.

## The write-up

`index.qmd`, drafted before the review and rewritten after it (step 9), in the Asta voice (<https://github.com/allenai/design/blob/main/asta/VOICE.md>), with headings that are nouns and are the same in every exploration:

1. **Headline.** A few sentences: what came back, and what could not be answered.
2. **Mission.** The mission in a sentence or two; when there was a message, quote it, lightly edited and anonymised.
3. **Data.** What the extract is, as AutoDiscovery was told, and what was not available.
4. **Runs.** One sentence: how many runs and experiments. Then the template's `::: {.runs}` block, which `_extensions/runs/runs.lua` fills at each render: one outlined box per run folder showing the prompt (cut at 300 characters, the whole of it on hover) and links to the hosted run and its `experiments.csv`, with every experiment in a collapsed table beneath, rises in belief first. The outlines take Asta's accent color.
5. **Findings.** The results worth calling out, each led by the experiments that found it in their words and with their figures, with why it matters for the mission and how far to trust it, as prose. In the draft, each ends with **What to check**.
6. **Null results.** What was tested and came back with nothing, and what could not be tested.
7. **Next steps.** From the review: what the team marked `Follow up` or `Validate`, then the data that would open up more. The write-up does not make those calls itself.

The template's placeholders are in square brackets; replace every one, and do not write placeholders in angle brackets, which render as nothing. Every number from an experiment carries a marker, `[text]{.ev key="..."}`, whose entry in `evidence.yml` quotes the experiment's own words verbatim from its run's `experiments.csv` (`Hypothesis`, `Findings` or `Validity Check`), names it as `AutoDiscovery run <label>, experiment <ID>`, and links the run's shared link with `?exp=<ID>`. Do not cite an ID that appears twice in a run; its link opens only one of the pair. Let the experiments speak first; literature, if a result needs context, is a targeted search quoted and linked. Figures are the experiments' own, from `.asta/autodiscovery/<run>/figures/`, looked at before use and copied into `figures/`, and never one mark per unit below the published level of geography. A term such as an odds ratio is defined the first time it is used.

## Records

Tracked: the mission, the extraction script, each run's folder (`run.md` and `experiments.csv`), each run's full record under `.asta/autodiscovery/` (`results.json`, or the local CLI's output folder: every experiment's plan, code, printed output, beliefs and figures) with its figures, and the write-up with its evidence and figures. The repository does not depend on the service keeping the runs. Not tracked: the source data and the extract.

## This folder

```
README.md           this workflow
templates/          _quarto.yml, index.qmd, mission.md, README.md, gitignore; _extensions/runs, the filter that draws
                    every run and its experiments into the write-up; and _extensions/evidence, the workspace evidence
                    extension with the marker-after-claim popover, carried here until the plugin release the project
                    pins ships it; delete that copy then and let the Makefile fetch it
scripts/runlog.py   each run's experiments.csv and figures from its saved record
```
