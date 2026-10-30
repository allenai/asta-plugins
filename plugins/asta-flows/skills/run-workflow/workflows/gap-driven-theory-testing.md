# Gap-Driven Theory Testing

Map what the literature knows and does not know about a question. Build theories that aim at the gaps. Test each theory on a dataset the papers did not use. For each theory the data cannot test, name the experiment or data that would.

This workflow reuses [Theory generation](theory-generation.md) for the papers and theories, and the verdict rules of [Secondary reproduction](secondary-reproduction.md) for the tests. It adds three things: the gap map, theories aimed at named gaps, and a record of the data each untested theory still needs.

It differs from [Data Driven Theory Generation](data-driven-theory-generation.md) in order. There, experiments run first and the theories explain them. Here, the theories and their predictions are fixed first and the data tests them. A prediction written before the data is seen is a real test. A theory fitted to the data afterwards is not.

## Plan

| Name | Description | Configuration |
|---|---|---|
| 1. Plan and papers | Theorizer plans a search and a schema that records what a gap map needs; Paper Finder, the person's local paper index, or both, gather the papers | 100 papers in total |
| 2. Extract | Theorizer extracts the schema from every paper, once | extraction `gpt-6-luna` |
| 3. Field standards | The agent learns how the field tests hypotheses and writes, from the corpus and up to 5 methods-guidance papers, into a recipe the later steps follow | up to 5 guidance papers, in a separate project |
| 4. Gap map | Theorizer sweeps the extraction for gap-shaped statements; the agent adds what the papers state as open, searches Paper Finder for each candidate gap, and drops those already answered | 6 sweep runs; one Paper Finder search per candidate gap |
| Check-in | Shows the gap map and a summary of the recipe; the person picks the gaps to target, and may correct the recipe | |
| 5. Theories | Theorizer generates theories aimed at the chosen gaps, from the same extraction, with the gap map as its mission | generation `gpt-6-sol`; one general pass, then one sweep run per Theorizer type the gaps call for |
| 6. Theory cards | The agent writes a card for each theory: rationale, known, unknown, proposal, how it closes the gap, supporting and falsifying experiments with the techniques that make them feasible, and all related evidence | committed before any data is opened |
| 7. Data and testability | Takes the person's datasets, finds more with Data Search if needed, and judges which predictions each can decide | the person's datasets, plus any found during the run |
| 8. Tests | Runs the committed tests and audits them; AutoDS may explore alongside | one test per prediction; AutoDS optional, 10 experiments |
| 9. What is missing | Specifies the experiment or data each undecided prediction needs | |
| 10. Revision (optional) | Theorizer revises the theories against the verdicts | verdicts as mission statement |
| 11. Report | A written report in the person's format, or by default a review-article report: what the literature knows, the gaps with their provenance, the theories, the test results, and the data and experiments still needed; then a short summary in the reply | `report.md`; reply under 300 words |

> You can make the run more specific:
>
> - **Gaps:** Gaps you already know matter, or gaps to leave out?
> - **Data:** Datasets you have or have in mind, such as your own files, a cohort, a portal or a paper's deposit? You can also add datasets later in the run.
> - **Theory shape:** A threshold equation, an "if–then" rule, or another form?
> - **Papers:** A local paper index to search, and whether it is the whole corpus or adds to Paper Finder?
> - **Writing style:** Papers whose writing the report should follow? By default it follows the style of the papers in the run.
> - **Report format:** A format for the final report, such as a journal's review style, a grant section or your lab's template? By default it is a review-article report.

## Papers from a local index

The person may have a local paper index: an asta-documents index built with the `local-paper-index` skill, or a folder of PDFs or markdown. It can be the whole corpus, or it can add to Paper Finder.

- **The `asta` CLI** searches the index. If `command -v asta` finds nothing, install it as the `asta-cli` skill in asta-tools shows. Without it, the run can still import the index's markdown files with `theorize papers import`, but cannot search them.
- **No index yet, only files.** Import them directly with `theorize papers import <folder>`. Build an index with `local-paper-index` only if the collection is large and only part of it bears on the question.
- **Search the index** with the plan's search query, and with one query per angle on the question:

  ```bash
  asta documents --root <index root> search --summary="<query>" --tags="<collection>" --show-scores
  ```

  The index holds chunks of about 2,000 characters, so one paper returns several hits. Group the hits by the document's `url`, the paper's markdown file, and rank papers by their best chunk. Read the top chunks of borderline papers before keeping them.
- **Import the kept papers whole.** Theorizer extracts from full papers, not chunks:

  ```bash
  theorize -p <run>/theory papers import <the kept markdown files>
  ```

  Import the markdown the index points to. If it has a `source_pdf` and the markdown is poor, import the PDF instead.
- **Combine with Paper Finder.** Unless the person says the index is the whole corpus, run Paper Finder for the rest of the target. Remove papers that appear in both, by DOI or title. If Paper Finder ranks a paper highly that the index lacks, keep it: the index reflects what the person collected, not the whole field.
- **Record the source of each paper,** local or Paper Finder, in `<run>/papers.md`. Mark local papers that are unpublished or not peer-reviewed. In the gap map, a known that rests only on unpublished local papers is listed as *thin*, not known.

## Datasets from the person

The person can give datasets at any point: with the question, at the check-in, or after the report. Each one goes into `<run>/data/<name>/` with its own description and test results.

- **Keep it out of the theories.** A dataset given early is not opened, described or shown to Theorizer until the theory cards are committed in step 6. Only its file names and a one-line summary from the person go into the plan. If the person wants their data to shape the theories, that is [Data Driven Theory Generation](data-driven-theory-generation.md), not this workflow.
- **Check independence.** Compare it with the corpus: same cohort, site, authors, accession or deposit as a paper the theories rest on? If yes, it is not an independent test. Say so, and report its results as consistency checks only.
- **Describe it from its own documentation and the file.** Use Data Driven Theory Generation's step 2. Ask the person for a codebook or README when a column the predictions need has none; do not guess its meaning.
- **A dataset given after the report** re-enters at step 7. The committed predictions stay unchanged. Re-judge testability, run steps 8 and 9 for it, and update the report: which undecided predictions it decided, and which remain.
- **Several datasets.** Test each prediction on each dataset that can decide it, separately. Report agreement across datasets. Do not pool them unless the person asks and the measures are the same.

## Identifying gaps

A gap is a question the field has reason to ask and has not settled.

**Start from the competing accounts.** Most questions name, or imply, rival answers ("content, gain, or adaptation?"). Before listing anything, write each account and what it predicts for each condition the question names. Every known then says which account it supports or rules out, and every gap says which accounts its answer would separate. A gap that separates no account is a moderator (a setting, layer or population); keep it, ranked lower.

The gap map has two lists:

- **Known:** a finding reported by at least two independent studies, in agreement. Write it from the extraction rows: the setting (design, stimulus or condition, population, area), the effect with its statistic and size, the sample (and whether inference was across animals or subjects, or across cells or trials), and the accounts it bears on. A preprint and its published version are one study.
- **Gap:** a question the papers ask but do not settle, of one of these kinds:

  | Kind | What it looks like | Where to look |
  |---|---|---|
  | *conflicting* | studies disagree | results that point in opposite directions; record what differs between the studies (population, method, measure, dose, setting), since that difference is the lead a theory follows |
  | *thin* | one study, a small sample, no replication, one lab, or observational evidence only | sample sizes and designs in the extraction; a claim many papers cite that rests on one study |
  | *untested link* | each part is known, but the link between them is assumed, not measured | chains of findings: A→B and B→C are reported, A→C or the mechanism is not |
  | *boundary* | known in one setting, untested in another | a table of populations or settings against outcomes; the empty cells |
  | *underpowered null* | a "no effect" result from a study too small to detect one | null results with their sample sizes; absence of evidence is not evidence of absence |

A question the papers raise as open, or one that follows from the knowns, is a gap of one of these kinds, not a separate list. Only list a gap that a paper points to; do not add questions from outside the corpus.

Gaps come from three sources, and the map uses all of them:

1. **What the authors say.** The limitations, future-work and open-question statements the extraction recorded.
2. **What the evidence shows.** Theorizer's sweep over the gap-shaped types (step 4): the state of the literature ("of N studies, K address Y and none address Z"), appraisals of evidence quality, context dependence, null results, disagreement between results, and critical appraisal of the evidence.
3. **What the agent sees across papers.** Chains of findings with a missing link, and empty cells in the table of settings against outcomes.

**A candidate is not a gap until Paper Finder has been asked about it.** The corpus is a sample of the field. A gap in 100 papers may be answered in the 101st. For each candidate, state it as a direct question and search for it:

```bash
theorize -p <run>/theory papers search "<the gap as a question, e.g. has X been measured in Y>" --save-as gapcheck-<id>
theorize -p <run>/theory load gapcheck-<id>
```

Nothing is fetched; the save holds each candidate paper's relevance (0 to 3), abstract and TL;DR. Read the abstracts of every paper rated 2 or 3:

- **Answered:** a paper addresses the question directly. Drop the gap, or narrow it to what that paper leaves open.
- **Partly answered:** papers address a neighbouring question (another population, another measure). Keep the gap and name those papers; they are what a theory must stay consistent with.

In both cases, fetch those papers into the corpus (`theorize papers fetch <corpus id> ...`), so the theories see them, and run `theorize extract` again once all the searches are done; per-paper results are checkpointed, so the rerun extracts only the new papers.
- **Not answered:** no paper rated 2 or 3 addresses it. Keep the gap, labelled "not found after a targeted search", never "no study exists".

Write each gap as:

```
[G3, boundary] Does <effect> hold in <setting>?
  accounts: <what each account predicts; which accounts the answer separates>
  rests on: <paper tags, with the result each contributes>
  targeted search: <search ID> -- <not answered | partly answered by <first author year, abstract>>
  would close it: <the evidence that would settle it>
```

**Rank the gaps** by a stated rule, and show the scores in a table. Score each gap from 0 to 2 on three things:
- **discrimination:** 2 if its answer separates all the accounts, 1 if it separates one from the rest, 0 for a moderator;
- **evidence state:** 2 if no study tests it, 1 if partly answered, 0 if mostly answered;
- **testability:** 2 if existing data can test it, at least through a proxy, 1 if it needs a new experiment with known techniques, 0 if no known technique exists.

Break ties by discrimination, then evidence state, and say how any remaining tie was broken.

**Cite by DOI.** Tag full-text corpus papers (P1, P2, ...). Cite abstract-only papers by first author, year and "abstract". Give a source table with each paper's tag or label, title and DOI, taken from the paper's metadata. Never cite by a search engine's internal ID. Mark a result a paper only reports from another study as "cited within P2".

**Keep a search log** in the map: for each search (the corpus search and every targeted search), its ID, purpose (corpus, or which gap), the exact query, the date, the number of results and of relevant results (rated 2 or 3), the outcome, papers added to the corpus, and the file it was saved to.

## Steps

The run directory holds `theory/` (the Theorizer project), `papers.md`, `plan-mission.md`, `methods/` (the guidance project), `field-standards.md`, `gaps.md`, `mission.md`, `theories/`, `data/`, `tests/`, `missing.md` and `report.md`.

1. **Plan and papers.** Plan once, with a mission that asks the schema for what a gap map needs. Put the theory shape, if the person gave one, into the question: the plan's request is the theory query the generator reads.

   ```bash
   theorize -p <run>/theory init --model gpt-6-sol --extraction-model gpt-6-luna
   theorize -p <run>/theory plan "<the question>" --mission-statement "$(cat <run>/plan-mission.md)"
   ```

   `<run>/plan-mission.md`:

   ```
   This run maps what the literature knows and leaves open about the question, then builds
   theories aimed at the gaps. Besides the findings themselves, the schema must record for each
   finding: the population or system and the setting; the study design; the sample size; the
   effect, its direction and its size; any result that conflicts with another study's; and the
   limitations, future work and open questions the authors state. For each test of a claim, it
   must also record the methods: the statistical test; how the null distribution was built
   (parametric, permutation or shuffle, surrogate data, bootstrap, simulation); the controls
   (positive, negative, sham, vehicle, scrambled); the unit of analysis and the number of
   independent units; the correction for multiple comparisons; the effect-size metric; the
   significance threshold; power or sample-size reasoning; and the robustness checks.
   ```

   **Check the plan before going on.** When a model call fails, `theorize plan` can still save a plan with no search query and no schema, and print its usual next step. Both of these must exit 0 and print something non-empty: a search query, and a list of schema fields that includes the methods fields the mission asked for.

   ```bash
   theorize -p <run>/theory load plan --key output.paper_search_query
   theorize -p <run>/theory load plan --key output.extraction_schema
   ```

   If either fails or is empty, stop. Read the error above the plan's output (often a model the endpoint does not serve), tell the person, and run the plan again once it is fixed. Check every later plan the same way, such as `plan-gaps` in step 5.

   Then gather papers from the local index, Paper Finder (Theory generation's step 2), or both, as [Papers from a local index](#papers-from-a-local-index) describes. Say how many papers came from each source, out of the target.

2. **Extract,** once:

   ```bash
   theorize -p <run>/theory extract
   ```

   This is the run's only extraction, unless step 5 needs a field it did not record.

3. **Field standards.** Learn how the field builds and tests its claims, and how it writes, so the tests and the report meet its standards. Write `<run>/field-standards.md`, the recipe steps 6 to 11 follow. This step reads the extraction and runs alongside the gap map.

   - **Practice, from the corpus.** From the methods fields of the extraction, tabulate for each kind of claim the papers test (a group difference, a correlation, a dose–response, a time series, a classification, and so on) what the papers do: tests, null distributions, controls, units of analysis, corrections, effect-size metrics, thresholds, robustness checks. Count, for example "permutation null in 34 of 60 papers testing a correlation".
   - **Guidance, from up to 5 methods papers.** Common practice is not always good practice. Search Paper Finder, in a separate project so these papers stay out of the theories' corpus, for the field's own guidance on statistics and reporting:

     ```bash
     theorize -p <run>/methods init --model gpt-6-sol --extraction-model gpt-6-luna
     theorize -p <run>/methods papers search "statistical best practices and reporting guidelines in <field>" --save-as guidance-1
     theorize -p <run>/methods papers search "common statistical errors in <field> research" --save-as guidance-2
     theorize -p <run>/methods papers fetch <corpus ids>
     ```

     Keep only papers whose abstracts show they are guidance for this field: a reporting guideline or checklist, a statistics tutorial, or a review of statistical practice. Fetch at most 5, and read their full text in `<run>/methods/paperstore.json`. If none exist, say so: the recipe then rests on the corpus's practice alone.
   - **Writing, from the corpus or the person's papers.** By default, learn the style of the papers in the run: section structure, terminology and nomenclature, units, how results are stated (for example "mean ± s.e.m., n = 12 mice"), how far claims are hedged, which figures are standard, and which metrics and statistics the field reports. Name two or three well-cited papers from the run as style models. If the person gave papers whose writing to follow, import them into `<run>/methods` with `theorize papers import` and use them instead. Follow their style, never their sentences.

   `<run>/field-standards.md`:

   ```
   # Field standards: <field>

   ## Hypothesis testing, per kind of claim
   ### <kind of claim, e.g. group difference>
   - test statistic and null distribution: <what> -- practice: <k of n papers, tags>; guidance: <tags or none>
   - required controls: ...
   - unit of analysis: ... (and how pseudoreplication is avoided)
   - correction for multiple comparisons: ...
   - effect-size metric, and the size the field treats as meaningful: ...
   - threshold: ...
   - robustness checks: ...
   - standard figures: ...

   ## Where practice and guidance differ
   - <the difference>; this run follows <which>, because <reason>

   ## Writing
   - style models: <tags>
   - structure, terminology, units, reporting of statistics, hedging: ...
   - metrics and statistics the field reports: ...
   ```

   Every rule names its papers. Where practice and guidance differ, follow the guidance and say so. Where the field is stricter than this workflow, follow the field; where this workflow is stricter, such as committing predictions before the data is opened, keep the workflow's rule. If the question spans fields, follow the field of the data the theories are tested on, and say which.

   Show a summary of the recipe at the gap map's check-in: one line per kind of claim, the main differences between practice and guidance, and the style models. The person may correct it. Do not wait for approval of the recipe itself; go on when the gaps are picked.

4. **Gap map.** Sweep the extraction for gap-shaped statements, one run per type:

   ```bash
   theorize -p <run>/theory theories sweep \
     --output-types "STATE OF THE LITERATURE" --output-types "APPRAISAL OF EVIDENCE QUALITY" \
     --output-types "CONTEXT DEPENDENCE" --output-types "NULL RESULT" \
     --inference-types "CONTRAST ARGUMENT (HETEROGENEITY)" --inference-types "CRITICAL APPRAISAL OF THE EVIDENCE" \
     --max-data-tokens 750000 --mission-statement "<the question>. Map what this literature has not settled: where results disagree and why, what has not been studied, and where the evidence is weak. Cite the findings each statement rests on." \
     --save-as gap-sweep
   theorize -p <run>/theory show gap-sweep
   ```

   The sweep's statements land in the project's theory store with the theories; read them by their save, `gap-sweep`, not with `show theories`. Each comes with supporting and conflicting evidence, which is where its paper tags come from.

   Then build `<run>/gaps.md` as [Identifying gaps](#identifying-gaps) describes: merge the sweep's statements with what the authors state as open and what you see across papers, search Paper Finder for every candidate, and write each kept gap in the format shown there.

   **Check the map before showing it.** Because it rests partly on your reading, check it against the run's files:
   - every entry cites at least one paper tag, and every known cites at least two from different studies;
   - every tag appears in `theorize -p <run>/theory show papers`;
   - every gap has its targeted search recorded;
   - every entry matches the extraction rows of the papers it cites. A subagent given only `gaps.md` and the extractions is the cleanest check. Correct or drop any entry the rows do not support, and say how many you dropped.

   **Check in and wait.** Show the gap map, ranked, with how many candidates the targeted searches dropped, and the recipe's summary from step 3. The person picks the gaps the theories should aim at. *Thin* and *underpowered null* gaps call for data, not a theory: offer to send them straight to step 9. If the person asked to run without check-ins, pick the top-ranked gaps a theory could close, and say which you picked.

5. **Theories.** Write the chosen gaps into `<run>/mission.md` in the shape below, then generate from the same extraction: one general pass, then a sweep over the Theorizer types the chosen gaps call for.

   | Gap kind | Output type | Inference type |
   |---|---|---|
   | conflicting | `CONTEXT DEPENDENCE` | `CONTRAST ARGUMENT (HETEROGENEITY)` |
   | boundary | `CONTEXT DEPENDENCE` | `ARGUMENT FROM ANALOGY` |
   | untested link | `MECHANISTIC EXPLANATION` | `ABDUCTION (BEST EXPLANATION)` |

   ```bash
   theorize -p <run>/theory theories generate --max-data-tokens 750000 --mission-statement "$(cat <run>/mission.md)" --save-as theories-gaps
   theorize -p <run>/theory theories sweep --output-types "<type>" --inference-types "<type>" --max-data-tokens 750000 --mission-statement "$(cat <run>/mission.md)" --save-as theories-gaps-typed
   ```

   Give the sweep only the types the chosen gaps call for, each once. If every chosen gap is of one kind, its two types are the whole sweep.

   The mission, in `<run>/mission.md`. Theorizer's generator already asks each theory for its scope, special cases, conflicting and unexplained evidence, and novelty, so the mission carries only what it lacks: the gaps, their evidence, and what a theory owes them.

   ```
   <the question>

   TARGET GAPS. Each theory must aim to close at least one gap below and name it by its ID in
   the theory's name. A theory that restates a known finding, or explains the corpus without
   touching a gap, is not what this run needs.

   GAPS:
   - [G1, conflicting] <the gap as a question>
       evidence: <what each side found, with tags>
       differs between the studies: <population, method, measure, setting>
   - [G2, untested link] <the gap as a question>
       evidence: <the known parts of the chain, with tags>

   KNOWN (a theory must stay consistent with these, or say which one it overturns and why):
   - <finding, population, effect size, tags>

   WHAT EACH THEORY MUST GIVE:
   - its rationale: how the known findings lead to it, and why it is the explanation the gap
     calls for;
   - what it proposes: the variables, by name, each something that can be measured; the
     direction, and the form where possible (threshold, monotone, interaction);
   - how it closes the gap: which answer to the gap's question it commits to;
   - an experiment whose result would support it, and one whose result would falsify it, each
     in a setting where it has not yet been tested.
   ```

   **Check scale.** Set aside, and say why, any theory too broad to fail ("X influences Y"), any that only restates one study, and any that names no gap. A theory is at the right scale when one study, or one dataset, could decide its prediction, and deciding it would settle the gap it names.

   **A second extraction only if needed.** If a chosen gap needs a variable the extraction did not record (check with `theorize -p <run>/theory show plan`), plan again with `mission.md --save-as plan-gaps` and check it as in step 1, extract with `--schema plan-gaps --schema-id schema-gaps --save-as extraction-gaps`, and generate from that extraction with `--extraction extraction-gaps`. Say so, and say what it costs: one more pass over every paper.

   Read the theories from their saves (`theorize show theories-gaps`, `theorize show theories-gaps-typed`). Cluster them by the gap they close and the explanation they give, as in Theory generation's step 7.

6. **Theory cards.** Write a card for each kept theory, in `<run>/theories/<id>.md`. Theorizer's output gives part of it: the statement, scope and special cases; the supporting, conflicting and unaccounted-for evidence; and what already exists, from its novelty evaluation. Write the rest from `gaps.md` and the extraction. Every claim on the card names its paper by tag. If the paper only reports another study's result, in its introduction or discussion, write "cited within P2", not "P2"; Theorizer's evidence often files such results under the reporting paper's tag.

   ```
   # <theory name> -- closes <gap IDs>

   ## Rationale
   How the known findings lead to this theory, step by step, and why it is a better answer to
   the gap than its main rival. Name the rival.

   ## What is known
   The findings the theory builds on and must stay consistent with: finding, population,
   effect size, tags. Note any known finding the theory overturns, and why.

   ## What is unknown
   The gap or gaps it targets, by ID, as questions, with the result of each gap's targeted
   search.

   ## What the theory proposes
   The statement; the variables, each measurable; the direction and form; the scope; where it
   should fail.

   ## How it closes the gap
   Which answer to each gap's question the theory commits to, and which experiment result
   below would settle it.

   ## Supporting experiments
   Experiments whose predicted result would support the theory. A result counts as support
   only if the main rival predicts otherwise.

   ## Falsifying experiments
   Experiments whose result would refute the theory. At least one per theory; a theory no
   experiment could falsify fails the scale check.

   ## Evidence
   Every piece of related evidence, none left out: supporting, conflicting, and unaccounted
   for, from Theorizer's output and the gap map, each with its tag and a one-line summary.
   ```

   Give each experiment, supporting or falsifying, these parts:
   - **Design:** the system or population, what is varied or compared, and what is measured.
   - **Prediction, committed:** the measured quantity, the statistic and its null distribution, the controls, the unit of analysis, the direction, and the threshold (significance and smallest effect that counts), each as `field-standards.md` gives it for this kind of claim. For a falsifying experiment, the result that would refute the theory.
   - **Feasibility:** the list of known techniques that make the experiment possible: for measuring each variable, for manipulating it if the design calls for that, and for the analysis. For each technique, give what it does in this experiment, a paper in the run that used it (tag), and its limits (resolution, scale, cost or access) as that paper reports them. If no paper in the run uses a technique for a variable, search Paper Finder for one (`theorize papers search "methods for measuring <variable> in <system>" --save-as techcheck-<id>`) and cite each technique the abstracts name by the paper's corpus id, marked "from abstract". If none is found, write "no known technique found". That is a finding: the experiment is not feasible yet, and the card says so.

   An experiment supports a theory; it does not prove it. Use "support" and "falsify" on the card, never "prove".

   **Check the cards** as the gap map is checked: every tag is in the run, every known and gap matches `gaps.md`, and every technique's paper reports using it. A subagent given only the cards, `gaps.md` and the extraction is the cleanest check.

   Commit the cards before opening any data. Do not change the predictions after; later steps add results beside them.

7. **Data and testability.** Start with the person's datasets (see [Datasets from the person](#datasets-from-the-person)). If they leave predictions untested, or the person gave none, Data Search finds more data independent of the corpus: a different cohort, site, instrument, period or method from the studies the theory was built on. Use Data Driven Theory Generation's step 2 to find, describe and measure the data. Then judge each prediction:
   - **testable:** the data has the same quantity, enough independent units at the expected effect size, the controls and unit of analysis `field-standards.md` requires, and a positive control that recovers a known effect;
   - **proxy:** the data has a related quantity; test it, and carry the proxy as a caveat;
   - **not testable,** with one reason: *no data*, *underpowered*, or *not identifiable* (the data cannot separate the claim from a rival explanation, or the relation is true by construction).

8. **Tests.** Run exactly the committed test for each testable prediction. A subagent given only the design and the data is the cleanest way. Record effect size, p, n, the code and a figure in `<run>/tests/`. Build the null distribution and run the controls as `field-standards.md` gives them, and report the effect in the field's metric. Then audit each result with a negative control for an effect, a positive control for a null, and a check for influential points. Give each prediction a verdict from Secondary reproduction: supported, partly supported, opposite effect, rejected, or undecided with its reason.

   AutoDS may run alongside, with the theories' predictions as its `--intent`, to look for findings the committed tests did not ask about. Report its findings as exploratory, never as tests of the theories.

9. **What is missing.** For each prediction that no dataset could decide, and each *thin* or *underpowered null* gap sent here from the check-in, write the study that would decide it, in `<run>/missing.md`. For a theory, start from its card's supporting and falsifying experiments and their feasibility; for a gap, write the experiment and its feasibility in the same form. Add:
   - **What to measure:** the quantity, its unit, and how it is measured; the system or population, and the setting.
   - **Design:** observational, intervention or natural experiment, with the field's standard controls from `field-standards.md`, and why it separates the claim from its main rival explanation. Name that rival. An observational design that cannot separate them is not enough; say what would.
   - **Size:** the number of independent units needed to detect the expected effect, in the field's effect-size metric, at the field's power and threshold (80 percent and alpha 0.05 if the field sets none), with the source of the expected effect size: a paper in the corpus by tag, or the smallest effect that would matter, said to be that. Do not invent an effect size.
   - **Existing data:** whether such data may already exist. Name a repository, cohort or deposit only if a paper in the corpus or a Data Search result points to it; otherwise say it must be collected.
   - **What each result would mean:** which outcome supports the theory, which refutes it, and which leaves it undecided.

   Link each one to the gap it would close. Then ask the person whether they have, or can get, such data. If they give it, it enters at step 7.

10. **Revision (optional).** Feed the verdicts back to Theorizer as the mission statement, as in Secondary reproduction's step 5. Theories that failed are evidence, not noise.

11. **Report.** Write `<run>/report.md`, then reply with a short summary.

    **Format.** If the person gave a format, follow it: its sections, order, length and citation style. Whatever the format, keep three things, in the place it allows: the provenance of every claim, what the run could not decide, and the confidence. If their format has no place for one of these, say so and add a short section for it at the end.

    **Default: a review-article report,** in the style of a Nature Reviews article. It is written as the field writes, following the writing section of `field-standards.md`: its terminology, units, statistics and metrics, and the style of its models. Expand every acronym on first use, keep tool names out of the text, and leave the run's machinery to an appendix.

    1. **Title and abstract.** A title that states the main finding. An abstract of about 150 words: the question, what is known, the main gaps, the theories, and what the tests found or could not decide.
    2. **Key points.** Four to six one-sentence points, each tagged as *known*, *gap*, *proposed*, *supported*, *refuted* or *undecided*.
    3. **Introduction.** Why the question matters, and the scope of the literature the run read: how many papers, from which sources, over which years.
    4. **What the literature knows.** A synthesis of the knowns, organized by theme, not paper by paper. Each finding with its population, effect size and citations. A table of the main findings where it helps.
    5. **Gaps.** A table of every gap the person chose, and a list of the others:

       | ID | Kind | The gap, as a question | Rests on | Targeted search | Would close it |
       |---|---|---|---|---|---|

       "Rests on" cites the papers. "Targeted search" gives the query and its result: not answered, or partly answered by the papers it names. Then a short paragraph per chosen gap on why it matters.
    6. **Theories.** One subsection per theory, from its card: the rationale, what it proposes, how it closes its gap, and its supporting and falsifying experiments with their feasibility. Cite the evidence for and against it. Point to the full card.
    7. **Tests on data.** A table of every committed prediction tested:

       | Theory | Prediction | Dataset | Effect size | n | p | Verdict |
       |---|---|---|---|---|---|---|

       Then the datasets: what they are, why they are independent of the papers, and their limits. Report exploratory AutoDS findings separately, labelled exploratory.
    8. **What remains: data and experiments needed.** From `missing.md`: each undecided prediction and each data gap, with the study that would decide it, the techniques that make it feasible, the sample size and its source, and whether the data may already exist. Experiments with no known technique are listed as not yet feasible.
    9. **Outlook.** What the field should do next, ranked: the one test that would settle the most, then the rest. End with the confidence in the run's main conclusion, as a label, with what might make it wrong.
    10. **References.** Every cited paper: authors, year, title, venue, DOI or corpus id, and its source (Paper Finder, local index, or targeted search). Mark unpublished and abstract-only sources.
    11. **Appendix: methods.** The question as run, the paper sources and counts, the extraction schema, the field standards the tests followed and their sources, the gap sweep, the targeted searches, the models, and what was dropped at each check and why.

    **Synthesis.** Sections 4 to 6 consolidate the literature; they do not list it.
    - **One claim per paragraph, several papers per claim.** Open with the claim, bring in the papers that support, qualify or contradict it, and close with what they establish together. A paragraph about one paper is kept for a study whose methods explain a disagreement between others.
    - **Three depths of treatment.** A few landmark papers get their design, effect size and limits. Most papers get two or three sentences inside a paragraph's argument. Replications are cited as converging evidence in one sentence. Do not give every paper the same depth.
    - **Conflicts stated, not smoothed.** Where papers disagree, say so in a marked block (`> **Conflicting evidence.**`): what each side found, with tags, and what differs between the studies. Every *conflicting* gap in `gaps.md` has one.
    - **Primary evidence for mechanisms.** A claim that X drives, gates, targets or mediates Y cites a paper that measured or manipulated it, not one that repeats it. If the run has no such paper, write "commonly described as" and say the primary evidence is missing from the run. That absence is a finding.

    **Provenance.** Every claim about the literature cites its papers. Every number comes from a paper in the run or a file the run wrote; name which. Nothing comes from outside the run. If a section needs a source the run does not have, the report says the run does not cover it.
    - **Cite only from the run.** Use only papers the run holds. If an argument needs a paper the run lacks, run a targeted search (as in step 4) or say the run does not cover it. Never add a citation from memory.
    - **The citation must make the claim.** The cited paper must report the claim, not only work on the topic. It must also point the same way: a paper reporting that a method is specific cannot support a claim that the method is unreliable.
    - **Numbers from the extraction only.** If the extraction states a result without a number, state it without a number.
    - **Authors from the references.** Take author names in the text from the reference list, which comes from the papers' metadata, never from memory. Mark secondhand results "cited within P2", as on the cards.

    **Check the report** before replying: every citation is in the references, every reference is in the run, and every number in the tables matches its file. Then check each claim–citation pair against the extraction rows of the paper it cites, and label it *supported*, *needs fix* (wrong paper, wrong direction, or a number not in the rows) or *cannot check* (the rows do not cover it). Fix or remove every *needs fix*. Also search the text for mechanistic verbs (drives, gates, targets, mediates, controls, modulates, inhibits) in sentences with no citation in that sentence or the next; cite or qualify each one. A subagent given only the report and the run directory is the cleanest check. Give the counts of the three labels in the methods appendix. If you have a tool for publishing artifacts, publish the report with it.

    **Reply,** under 300 words; the detail is in the report.
    - **Gap map,** in three lines: the competing accounts, the main known, and the top-ranked gap with the accounts it separates.
    - **Theories,** one line each: name, gap targeted, verdict, and its card's path.
    - **What the data could not decide,** and the study that would.
    - **Confidence,** as a label, with what might make it wrong.
    - **The report's path.**
