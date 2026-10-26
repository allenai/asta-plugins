# AutoDiscovery exploration

A team nominates a dataset they already work with and writes a short prompt about what they are curious about. AutoDiscovery searches the data and returns a ranked list of surfaced hypotheses. The team reviews the list together, decides what is worth a follow-up analysis or a small validation effort, and writes up what came back, including a null result. This workflow takes a team from the dataset to the write-up, and leaves the record the collaboration asks for: the extraction script, the seed prompts, a log of each run, and the write-up, in one version-controlled repository.

The researcher's part is the prompt and the review. AutoDiscovery does not find much without a strong seed prompt, so the workflow stops before any run is created and settles the prompts with them, and stops again before the write-up is published. Budget an hour or two of their time for those two conversations.

## Setup

```bash
asta auth login                 # once; the runs use the hosted service
asta autodiscovery credits      # the balance has to cover the budget
```

The project is an Asta workspace (the `workspace` skill): a git repository that renders to a site, one exploration per repository. A follow-up on the same data is a later round in the same repository. The repository is the team's, in their own organisation and private when the data terms say so; nothing in the workflow depends on where it lives. The site is published where the team publishes, a public unlisted site, a private one, or not at all: the rendered site is a folder of HTML that can be shared by hand.

Data stays where it belongs. AutoDiscovery sees a de-identified or aggregated extract, and restricted row-level data never enters git. When the extract may not be uploaded to the hosted service, the team brings its own keys: the autodiscovery skill's local workflow runs the `asta-autodiscovery` CLI on their machine against the model their key points at, with no credits. Say once that this model receives the data descriptions, the generated code and its printed output, as with any use of that key, and leave the choice of model to the team; it is theirs to make under their own data terms, so do not propose other providers or a smaller extract unless asked. The record is the same: point the CLI's `--out_dir` at `autodiscovery/<run>/local/`, put `local` in the run log's run id column, and `runlog.py` reads it as it reads a hosted run. The write-up's markers link to the run pages; the hosted-experiment links are simply absent.

## Plan

Show the person this table with the values for their dataset. Anything not in it runs on the service's defaults.

| Name | Description | Configuration |
|---|---|---|
| Nominate the dataset | Set up the repository and look at the data | the repository the person names |
| Seed prompts | Turn the prompt into seed prompts, one per run, with a budget and an extract | 250 credits by default |
| Seeding conversation | The researcher settles the prompts, the budget and the extract before any run exists | |
| Extract and describe | Build the extract and describe it for AutoDiscovery | |
| Run AutoDiscovery | Run, save the ranked list of surfaced hypotheses, log each run | one open run plus the planned runs, 40 to 60 experiments each |
| Write up | The write-up, including null results; the data page and a page per run | |
| Check and publish | Check the quotes and claims; show the researcher; publish | |

After the table, list what they can change:

> - **Budget:** 250 experiments by default (credits on the hosted service; model cost with your own keys); more buys deeper or more runs.
> - **Runs:** merge or split the proposed runs, or add a question.
> - **Data:** a different extract, or more columns.

The workflow is collaborative. Even when the person asks for it to run on its own, the seeding conversation and the look at the write-up are theirs.

## Steps

1. **Nominate the dataset.** Scaffold the repository with the `workspace` skill, then copy this folder's `templates/` over it (the site config, the write-up, the data page, the README, `questions.md`, the ignore rules and the two CSV headers) and its `scripts/` into `scripts/`. Then look at the data before proposing anything: what the files or tables hold, how the data were collected (weights, clusters, strata, arms), and what the prompt would need that is not there. Keep the notes in the repository; they are not a page. The template's `_quarto.yml` renders only the write-up, the data page and the run pages, and takes its sidebar from `_generated/sidebar.yml`, which `build_pages.py` writes; nothing else becomes a page.

2. **Seed prompts.** With the researcher's message and what you learned from the data:

   1. List each question or idea in the message as a sub-question, in their words.
   2. For each, name the outcome and the columns that could answer it. If there are none, say so, and what data it would need.
   3. Group sub-questions that share an outcome and a set of columns; each group is a run. Split a group that names more than about ten columns or needs a different file.
   4. Add one run with no question on the main file, as the control for the others.
   5. Write each run's seed prompt ([Seeding protocol](#seeding-protocol)).
   6. Spread the budget, 40 to 60 experiments per run; merge groups if there are too many.
   7. Write the coverage table in `questions.md`: each sub-question, its run, or why it has none.
   8. List the extract: the files each run needs and their columns, wider than the prompt suggests (step 3).
   9. Note, in a few lines, data not in the source that would change the plan, such as a record the researcher may hold. The run goes ahead with what is there; later data is a later round.

   When the researcher brings data and curiosity rather than questions, the data supplies the structure: its main areas become the runs, the open run takes a larger share of the budget, and a sentence or two from them on what they are curious about goes in `questions.md` in place of the sub-questions.

   Then the seeding conversation. Show the budget, the sub-questions, the runs with their files and experiment counts, the seed prompts, the coverage table, the extract, and the data that would change the plan. Ask what they would merge, split, drop or add, which sub-questions matter most, and whether they hold any of that data. Expect to revise. End with one question on its own line, such as "Create these runs, or change them?", and do nothing further until they answer.

3. **Extract and describe.** Write the extraction in whatever the team works in, Python, R, Stata, SQL or a notebook, and commit it, so the extract can be rebuilt. Record each file's row count and a hash. Extract more than the prompt suggests: AutoDiscovery can only use the columns it is given. Keep the design variables, and include a second outcome that is measured the same way but has a different cause when the source has one; it lets a reader tell a result about the mechanism from one about the measurement.

   Describe each file for AutoDiscovery: what a row is, each column's meaning, units, coding and missingness, the design, technical cautions. Say what the data are, not what they show. No thresholds, definitions or derived outcomes that belong to the question; derived covariates are fine with their formula. Write each run's metadata and run the neutrality check over every prompt and description.

4. **Run AutoDiscovery.** For each run: `asta autodiscovery create`, `upload` the files, `metadata` from the file, `metadata-get` to confirm name, prompt, files and experiment count match, then `submit`. Submit the runs together; a run of 50 takes about two hours. Poll until they finish. Save each run's results under `autodiscovery/<run>/results.json` (`asta autodiscovery results`), then `scripts/runlog.py` writes the run log, the ranked list and each run's index ([The run log](#the-run-log)); it keeps code, printed output and id lists out of the tracked files and stops if a hypothesis or analysis looks like row-level data. Share each run in the AutoDiscovery app, then open one experiment link in a private window to confirm it needs no sign-in.

5. **Write up.** `scripts/build_pages.py` writes the run pages, the write-up's runs table and the sidebar from the run log. Fill the data page and the write-up ([The pages](#the-pages)).

6. **Check and publish.** `scripts/check.py` checks the form (the CSV columns, every rendered page in the sidebar, the headings, every marker's quote verbatim with the shared link and a page, every internal link) and fails the build otherwise. Run the `check-claims` skill over the write-up. Render with `make check`, show the researcher the preview, and publish once they have seen it.

## Seeding protocol

A seed prompt says where to look. It names an area and the columns in scope, and a contrast when the sub-question asks for one. It does not name a mechanism, a direction, an effect size or an earlier result, and neither does the description: AutoDiscovery told what to find tends to find it.

```
Explore <area> in relation to <outcome columns>: <the columns in scope, named or grouped>.
Compare <A> with <B>.                       (only when the sub-question asks for it)
```

One sentence on what the measurement can and cannot show may be added to every prompt, the same on each. The open run's prompt is one line: explore the data; there is no specific question.

Before anything is created, search every prompt, the run description and each file description's prose for direction and result words (`associated`, `higher`, `lower`, `more likely`, `less likely`, `increase`, `decrease`, `effect`, `odds`, `expected`, `predicts`, `known findings`), and the prompts for a per-project list of terms that would name a result. A grep is enough; it catches wording, not intent, so read the prompts once more.

## The run log

`autodiscovery/runs.csv`, one row per run: run, round, label, title, run id, prompt file, the sub-questions it covers, files, extract hash, experiments requested, the search settings as the service reports them, status, shared link, and a decision column left empty for the review. The first columns are filled by hand at step 2 (a short name, a one-letter label for the markers, a title) and the run id after `create`; `runlog.py` fills the rest.

`autodiscovery/experiments.csv`, the ranked list: one row per experiment, ordered within each run by the change in belief with rises first, with run, number, hypothesis, AutoDiscovery's analysis of what it found, belief before and after, surprisal, the service's surprising flag, and the link.

## The pages

Every page is a template in `templates/` filled in, in the Asta voice (<https://github.com/allenai/design/blob/main/asta/VOICE.md>), with headings that are nouns and are the same in every exploration.

**The write-up**, `index.qmd`:

1. **Headline.** A few sentences: what came back, and what could not be answered.
2. **Prompt.** The researcher's message as a quote, lightly edited and anonymised. The message as sent stays in `questions.md`.
3. **Data.** What the extract is, as AutoDiscovery was told, and what was not available.
4. **Runs.** One sentence: how many runs and experiments. Then the run log as a table with four columns, the prompt as submitted, the experiments, the run's page and its hosted run, with the two CSVs to download under it. A sentence that every prompt shares is shown once under the table rather than in every row. Nothing else. With more than one round, a sub-heading per round above its rows, and a line on what the round was for.
5. **Answers.** When the researcher asked questions: two columns, the question as a complete sentence in their words and the answer, which opens, in bold, with one of the collaboration's own phrases, worth a follow-up analysis, worth a small validation effort, or null result, and gives the one number that carries it with its marker. Where the data cannot answer the question, the answer says so in plain words with no label. The phrases are not defined on the page. A term such as an odds ratio is defined the first time it is used, here or wherever that is.
6. **Findings.** The results worth calling out, at your discretion, each led by the experiments that found it in their words and with their figures, with why it matters and how far to trust it, as prose. For an open exploration this section carries the page.
7. **Null results.** What was tested and came back with nothing, and what could not be tested.
8. **Next steps.** What to do next, on its own, with more than one entry when there is more than one way to follow up.

**The data page**, `data.qmd`: Source (the survey or study and how it was collected), Extract (why an extract rather than the source, which parts of the source it used and which it did not, what it keeps and what it leaves out, how it is rebuilt, and each file's version), Files (one paragraph per file: what a row is, how many, which runs received it), Description (the text every run received) and Columns (the table).

**A run page**, `runs/<run>.qmd`: the prompt as submitted, then Run (file, experiments, search settings, the hosted link) and Experiments (the run's rows from the ranked list, with links), with links to the previous and next run and back to the write-up.

Every number from an experiment carries a marker that opens the experiment's own words and links to the run page and the hosted experiment. Let the experiments speak first; literature, if a result needs context, is a targeted search quoted and linked. Figures are the experiments' own, looked at before use, and never one mark per unit below the published level of geography.

## Review together

The review is outside the workflow. The researcher and the team go through the write-up and the ranked list and decide, for each result, whether it is worth a follow-up analysis, a small validation effort, or nothing, and whether the page's own phrases stand. The decisions go in the run log's decision column and are what a later round starts from.

## Follow-up rounds

A later round is new runs in the same repository: new rows in the run log with the next round number, new run pages, and the write-up updated in place so the reader always gets one current answer. Each round is a pull request, and its preview shows what changed. Data that arrives later gets a new extract with its own hash.

## Records

Tracked: the extraction script and descriptions, the seed prompts, each run's metadata as submitted and as read back, the run log, the ranked list, the run pages, and the figures that passed review. Not tracked: the extract when the source is restricted, and the raw experiment records, which carry row ids, generated code and printed output; the service keeps them.

## This folder

```
README.md               this workflow
templates/              _quarto.yml, index.qmd, data.qmd, README.md, questions.md, gitignore, autodiscovery/runs.csv and experiments.csv (headers),
                        and _extensions/evidence, the workspace evidence extension with the marker-after-claim popover and the page field, carried
                        here until the plugin release the project pins ships it; delete the copy then and let the Makefile fetch it
scripts/runlog.py       the run log, the ranked list and each run's index from the saved results
scripts/build_pages.py  the run pages, the write-up's runs table and the sidebar from the run log
scripts/check.py        the form and the quotes; fails the build on any drift
```

The templates and the scripts are what keep explorations alike; the prose above is for the judgment calls.
