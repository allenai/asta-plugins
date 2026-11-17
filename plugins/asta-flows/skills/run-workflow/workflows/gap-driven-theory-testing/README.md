# Gap-Driven Theory Testing

Map what the literature knows and doesn't know about a question. Build theories aimed at the gaps. Test each one with AutoDS on a dataset the papers didn't use. For each theory the data can't test, name the experiment or data that would.

It's the reverse of [Data Driven Theory Generation](../data-driven-theory-generation/README.md). There, the experiments come first and the theories explain them. Here, the theories and their predictions are fixed first and the data tests them. A prediction written before the data is seen is a real test; a theory fitted to the data afterwards isn't.

The papers and theories are [Theory generation](../theory-generation/README.md)'s steps, and the verdicts are [Secondary reproduction](../secondary-reproduction/README.md)'s.

## Plan

| Step | What it does | Configuration |
|---|---|---|
| 1. Plan and papers | Theorizer plans a search and a schema that records what a gap map needs; papers from Semantic Scholar, the person's local index, or both | 100 papers |
| 2. Extract | Once, over every paper | |
| 3. Field standards | How the field tests claims and writes, from the corpus and up to 5 methods-guidance papers | a separate project for the guidance papers |
| 4. Gap map | Theorizer sweeps for gap-shaped statements; you add what the papers state as open; each candidate is searched for; answered ones drop | one search per candidate |
| Check-in | The person picks the gaps, and may correct the standards | |
| 5. Theories | Aimed at the chosen gaps, from the same extraction | one general pass, then a sweep per type the gaps call for |
| 6. Theory cards | A card per theory, with its supporting and falsifying experiments | committed before any data is opened |
| 7. Data and testability | The person's datasets, plus Data Search; which predictions each can decide | |
| 8. Tests | AutoDS runs the committed tests on the data; the verdicts are audited | one experiment per prediction |
| 9. What's missing | The study each undecided prediction needs | |
| 10. Revision (optional) | Theorizer revises the theories against the verdicts | |
| 11. Report | The report ([templates/report.qmd](../../templates/report.qmd)), written and then revised on what `check-claims` finds | |

> You can make the run more specific:
>
> - **Gaps:** Gaps you already know matter, or gaps to leave out?
> - **Data:** Datasets you have or have in mind, such as your own files, a cohort, a portal or a paper's deposit? You can also add datasets later in the run.
> - **Theory shape:** A threshold equation, an "if–then" rule, or another form?
> - **Papers:** A local paper index to search, and whether it is the whole corpus or adds to Semantic Scholar?
> - **Writing style:** Papers whose writing the report should follow? By default it follows the style of the papers in the run.
> - **Report format:** A format for the final report, such as a journal's review style, a grant section or your lab's template? By default it is the report template, with the gaps as its questions and the tests as its experiments.

## Papers from a local index

An index built with the `local-paper-index` skill can be the whole corpus or add to Semantic Scholar. Search it with the plan's query and one query per angle (the `asta-documents` skill). Hits are chunks, so group them by paper and rank papers by their best chunk. Import the kept papers whole, since Theorizer extracts from full papers. Unless the index is the whole corpus, fill the rest of the target from Semantic Scholar and remove papers in both. Record each paper's source in `papers.md`, and mark unpublished ones: a known that rests only on unpublished papers is *thin*.

## Datasets from the person

They can give datasets at any point. Each goes into `data/<name>/` with its own description and results.

- **Keep it out of the theories.** Don't open, describe or show it to Theorizer until the cards are committed. If they want their data to shape the theories, that's Data Driven Theory Generation.
- **Check independence.** Same cohort, site, authors, accession or deposit as a paper the theories rest on? Then its results are consistency checks only. Say so.
- **After the report,** a new dataset re-enters at step 7. The committed predictions don't change.
- **Several datasets:** test each prediction on each one separately and report agreement. Don't pool them unless asked and the measures match.

## Identifying gaps

A gap is a question the field has reason to ask and hasn't settled.

**Start from the competing accounts.** Most questions imply rival answers. Write each account and what it predicts before listing anything. Every known then says which account it supports or rules out, and every gap says which accounts its answer would separate. A gap that separates none is a moderator; keep it, ranked lower.

- **Known:** reported by at least two independent studies, in agreement, with its setting, effect, sample (and whether inference was across subjects or across cells or trials) and the accounts it bears on. A preprint and its published version are one study.
- **Gap,** one of:

  | Kind | What it looks like |
  |---|---|
  | *conflicting* | studies disagree; record what differs between them, since that's the lead a theory follows |
  | *thin* | one study, a small sample, no replication, or observational evidence only |
  | *untested link* | each part is known, but the link is assumed, not measured |
  | *boundary* | known in one setting, untested in another |
  | *underpowered null* | "no effect" from a study too small to detect one |

Gaps come from what the authors say is open, from Theorizer's sweep, and from what you see across papers (missing links, empty cells). Only list a gap a paper points to.

**A candidate isn't a gap until Semantic Scholar has been asked.** State it as a question and search. If a paper answers it, drop or narrow it; if papers answer a neighbouring question, keep it and name them. Either way add those papers to the corpus and extract again. If nothing answers it, label it "not found after a targeted search", never "no study exists".

```
[G3, boundary] Does <effect> hold in <setting>?
  accounts: <what each predicts; which the answer separates>
  rests on: <paper tags, with what each contributes>
  targeted search: <search id> -- <not answered | partly answered by <first author year>>
  would close it: <the evidence that would settle it>
```

**Rank the gaps,** 0 to 2 on each, in a table: *discrimination* (separates all accounts, one from the rest, or a moderator), *evidence state* (untested, partly answered, mostly answered), *testability* (existing data, a new experiment with known techniques, no known technique). Break ties by discrimination, then evidence.

**Cite by DOI,** tag full-text papers P1, P2, …, cite abstract-only ones by first author, year and "abstract", and mark a result a paper only reports from another study as "cited within P2". Keep a search log: each search's purpose, query, date, counts, outcome and file.

## Steps

1. **Plan and papers.** The Theorizer project is `<run>/01-plan-and-papers/theory`, with its searches beside it in `01-plan-and-papers/searches`; write its site data to `01-plan-and-papers/data/theorizer.json`, which the page's Papers section reads. Plan once, with this mission, and check the plan has a query and a schema with the methods fields:

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
2. **Extract,** once, in that project; a summary of what came out goes in `02-extract/`.
3. **Field standards,** in `field-standards.md`: for each kind of claim the papers test, what they do (tests, nulls, controls, units, corrections, effect sizes, thresholds, robustness), counted from the extraction's methods fields ("permutation null in 34 of 60"), never by keyword. Then what up to 5 of the field's own methods-guidance papers say, in a separate Theorizer project (`03-field-standards/theory`) so they stay out of the theories. Where practice and guidance differ, follow the guidance and say so. Add how the field writes, from two or three well-cited papers, or the person's. Every rule names its papers.
4. **Gap map,** in `gaps.md`: sweep for state of the literature, evidence quality, context dependence, null results, heterogeneity and critical appraisal (`generate-theories`; locally the output types `STATE OF THE LITERATURE`, `APPRAISAL OF EVIDENCE QUALITY`, `CONTEXT DEPENDENCE`, `NULL RESULT` and the inference types `CONTRAST ARGUMENT (HETEROGENEITY)`, `CRITICAL APPRAISAL OF THE EVIDENCE`). Sweep once, with the step-1 mission. The sweep's theories are gap candidates, not the run's theories: read them from what it returns and keep them out of the theory store. Then build the map as above. Then have a subagent given only the map and the extractions check every entry against the rows it cites, and apply its fixes; one run's check found wrong tags and a known that didn't hold. **Check in and wait** with the ranked map and the standards' summary. *Thin* and *underpowered null* gaps call for data, not a theory: offer to send them to step 9.
5. **Theories.** The chosen gaps go into the mission:

   ```
   <the question>

   TARGET GAPS. Each theory must aim to close at least one gap below and name it by its ID in
   the theory's name. A theory that restates a known finding, or explains the corpus without
   touching a gap, is not what this run needs.

   ACCOUNTS: <each competing account, and what it predicts>

   GAPS:
   - [G1, conflicting] <the gap as a question>
       evidence: <what each side found, with tags>
       differs between the studies: <population, method, measure, setting>

   KNOWN (a theory must stay consistent with these, or say which one it overturns and why):
   - <finding, population, effect size, tags>

   WHAT EACH THEORY MUST GIVE: its rationale; what it proposes, with measurable variables, the
   direction and the form; how it closes the gap; and an experiment that would support it and one
   that would falsify it, each in a setting where it has not yet been tested.
   ```

   Generate once and sweep once, each over all the chosen gaps, with the types the gaps call for: conflicting → context dependence and heterogeneity (`CONTEXT DEPENDENCE`, `CONTRAST ARGUMENT (HETEROGENEITY)`); boundary → context dependence and analogy (`ARGUMENT FROM ANALOGY`); untested link → mechanistic explanation and abduction (`MECHANISTIC EXPLANATION`, `ABDUCTION (BEST EXPLANATION)`). Save these to the theory store. Set aside any theory too broad to fail, any that restates one study, and any that names no gap; say why in `gaps.md`, and leave them off the site with `--exclude <their ids>`. If a gap needs a field the extraction lacks, plan and extract again, and say what it costs. Write each gap's theories for the site with `theorizer-site-data <the project> <run>/05-theories/data/theorizer-<ID>.json --gap <ID>`, which keeps the theories that name the gap.
6. **Theory cards,** one per theory in `06-theory-cards/<id>.md`: rationale (and the main rival), what's known, what's unknown, what it proposes, how it closes the gap, supporting and falsifying experiments, and all the related evidence. Each experiment has a design, a committed prediction (in the field's standards), and its feasibility: the known techniques for each variable, each with a paper that used it and its limits, or "no known technique found", which is itself a finding. Use "support" and "falsify", never "prove". Check the cards as the map was checked, then **commit them before opening any data.**
7. **Data and testability.** Each prediction is *testable*, *proxy* (tested, with the proxy as a caveat) or *not testable* (no data, underpowered, or not identifiable).
8. **Tests,** with AutoDS (the `autodiscovery` skill), in one run on the test data. Each committed prediction is one experiment, with the card's design and decision rule as its plan: locally as the CLI's warmstart seeds or as nodes you write with the library, remotely as the run's intent ("Test each of these as written: <the hypotheses and designs>"). Match each experiment to its card first: a prediction with no matching experiment, or one run with a different design, is undecided. Read each matched experiment against its committed decision rule and give Secondary reproduction's verdict; report AutoDS's belief change beside the verdict, never as it. Experiments AutoDS adds beyond the predictions are exploratory, never tests of the theories.
9. **What's missing,** in `missing.md`: for each undecided prediction and each data gap, what to measure, the design and the rival it separates, the sample size and where its effect size came from (never invented), whether such data may exist, and what each result would mean. Then ask the person whether they have such data.
10. **Revision,** optional: the verdicts as the mission, as in Secondary reproduction.
11. **Report,** in the person's format or [templates/report.qmd](../../templates/report.qmd)'s, with the gaps as its questions and the tests as its experiments. Write it, run the `check-claims` skill on it, and revise it on what that finds. The run's page is `templates/page.qmd`, with `{{RUN}}` set to the run's folder name, and its Theories and Tests shortcodes repeated once per chosen gap, with `<gap ID>` set to each.
