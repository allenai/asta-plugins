# Gap-Driven Theory Testing

Map what the literature knows and does not know about a question. Build theories that aim at the gaps. Test each theory on a dataset the papers did not use. For each theory the data cannot test, name the experiment or data that would.

This workflow reuses [Theory generation](theory-generation.md) for the papers and theories, and the verdict rules of [Secondary reproduction](secondary-reproduction.md) for the tests. It adds three things: the gap map, theories aimed at named gaps, and a record of the data each untested theory still needs.

It differs from [Data Driven Theory Generation](data-driven-theory-generation.md) in order. There, experiments run first and the theories explain them. Here, the theories and their predictions are fixed first and the data tests them. A prediction written before the data is seen is a real test. A theory fitted to the data afterwards is not.

## Plan

| Name | Description | Configuration |
|---|---|---|
| 1. Plan and papers | Theorizer plans a search and a schema that records what a gap map needs; Paper Finder, the person's local paper index, or both, gather the papers | 100 papers in total |
| 2. Extract | Theorizer extracts the schema from every paper, once | extraction `gpt-6-luna` |
| 3. Gap map | Theorizer sweeps the extraction for gap-shaped statements; the agent adds what the papers state as open, searches Paper Finder for each candidate gap, and drops those already answered | 6 sweep runs; one Paper Finder search per candidate gap |
| Check-in | Shows the gap map; the person picks the gaps to target | |
| 4. Theories | Theorizer generates theories aimed at the chosen gaps, from the same extraction, with the gap map as its mission | generation `gpt-6-sol`; one general pass, then one sweep run per Theorizer type the gaps call for |
| 5. Predictions | The agent turns each theory into committed predictions | before any data is opened |
| 6. Data and testability | Takes the person's datasets, finds more with Data Search if needed, and judges which predictions each can decide | the person's datasets, plus any found during the run |
| 7. Tests | Runs the committed tests and audits them; AutoDS may explore alongside | one test per prediction; AutoDS optional, 10 experiments |
| 8. What is missing | Specifies the experiment or data each undecided prediction needs | |
| 9. Revision (optional) | Theorizer revises the theories against the verdicts | verdicts as mission statement |
| 10. Report | The gap map, the theories with their verdicts, and the studies still needed | under 300 words; the detail is in the run's files |

> You can make the run more specific:
>
> - **Gaps:** Gaps you already know matter, or gaps to leave out?
> - **Data:** Datasets you have or have in mind, such as your own files, a cohort, a portal or a paper's deposit? You can also add datasets later in the run.
> - **Theory shape:** A threshold equation, an "if–then" rule, or another form?
> - **Papers:** A local paper index to search, and whether it is the whole corpus or adds to Paper Finder?

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

- **Keep it out of the theories.** A dataset given before step 5 is not opened, described or shown to Theorizer until the predictions are committed. Only its file names and a one-line summary from the person go into the plan. If the person wants their data to shape the theories, that is [Data Driven Theory Generation](data-driven-theory-generation.md), not this workflow.
- **Check independence.** Compare it with the corpus: same cohort, site, authors, accession or deposit as a paper the theories rest on? If yes, it is not an independent test. Say so, and report its results as consistency checks only.
- **Describe it from its own documentation and the file.** Use Data Driven Theory Generation's step 2. Ask the person for a codebook or README when a column the predictions need has none; do not guess its meaning.
- **A dataset given after the report** re-enters at step 6. The committed predictions stay unchanged. Re-judge testability, run steps 7 and 8 for it, and update the report: which undecided predictions it decided, and which remain.
- **Several datasets.** Test each prediction on each dataset that can decide it, separately. Report agreement across datasets. Do not pool them unless the person asks and the measures are the same.

## Identifying gaps

A gap is a question the field has reason to ask and has not settled. The gap map has three lists:

- **Known:** a finding reported by at least two independent studies, in agreement. Give the population or system, the effect and its size.
- **Gap:** a question the papers ask but do not settle, of one of these kinds:

  | Kind | What it looks like | Where to look |
  |---|---|---|
  | *conflicting* | studies disagree | results that point in opposite directions; record what differs between the studies (population, method, measure, dose, setting), since that difference is the lead a theory follows |
  | *thin* | one study, a small sample, no replication, one lab, or observational evidence only | sample sizes and designs in the extraction; a claim many papers cite that rests on one study |
  | *untested link* | each part is known, but the link between them is assumed, not measured | chains of findings: A→B and B→C are reported, A→C or the mechanism is not |
  | *boundary* | known in one setting, untested in another | a table of populations or settings against outcomes; the empty cells |
  | *underpowered null* | a "no effect" result from a study too small to detect one | null results with their sample sizes; absence of evidence is not evidence of absence |

- **Unknown:** a question the papers raise as open, or one that follows from the knowns and that no paper addresses. Only list an unknown that a paper points to; do not add questions from outside the corpus.

Gaps come from three sources, and the map uses all of them:

1. **What the authors say.** The limitations, future-work and open-question statements the extraction recorded.
2. **What the evidence shows.** Theorizer's sweep over the gap-shaped types (step 3): the state of the literature ("of N studies, K address Y and none address Z"), appraisals of evidence quality, context dependence, null results, disagreement between results, and critical appraisal of the evidence.
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
  rests on: <paper tags>
  targeted search: "<query>" -- <not answered | partly answered by <tags>>
  would close it: <the evidence that would settle it>
```

**Rank the gaps** for the check-in by three things, in this order: how far closing the gap would advance the person's question; whether a test is plausible with data that exists or could be collected; and how much evidence already surrounds it, since a gap with knowns on both sides is easier to theorize about than one in empty ground.

## Steps

The run directory holds `theory/` (the Theorizer project), `papers.md`, `plan-mission.md`, `gaps.md`, `mission.md`, `theories/`, `data/`, `tests/`, `missing.md` and `report.md`.

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
   limitations, future work and open questions the authors state.
   ```

   Then gather papers from the local index, Paper Finder (Theory generation's step 2), or both, as [Papers from a local index](#papers-from-a-local-index) describes. Say how many papers came from each source, out of the target.

2. **Extract,** once:

   ```bash
   theorize -p <run>/theory extract
   ```

   This is the run's only extraction, unless step 4 needs a field it did not record.

3. **Gap map.** Sweep the extraction for gap-shaped statements, one run per type:

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

   **Check in and wait.** Show the gap map, ranked, with how many candidates the targeted searches dropped. The person picks the gaps the theories should aim at. *Thin* and *underpowered null* gaps call for data, not a theory: offer to send them straight to step 8. If the person asked to run without check-ins, pick the top-ranked gaps a theory could close, and say which you picked.

4. **Theories.** Write the chosen gaps into `<run>/mission.md` in the shape below, then generate from the same extraction: one general pass, then a sweep over the Theorizer types the chosen gaps call for.

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
   - the variables, by name, each something that can be measured;
   - the direction, and the form where possible (threshold, monotone, interaction);
   - one prediction that would be false if the theory were wrong, in a setting where it has
     not yet been tested.
   ```

   **Check scale.** Set aside, and say why, any theory too broad to fail ("X influences Y"), any that only restates one study, and any that names no gap. A theory is at the right scale when one study, or one dataset, could decide its prediction, and deciding it would settle the gap it names.

   **A second extraction only if needed.** If a chosen gap needs a variable the extraction did not record (check with `theorize -p <run>/theory show plan`), plan again with `mission.md --save-as plan-gaps`, extract with `--schema plan-gaps --schema-id schema-gaps --save-as extraction-gaps`, and generate from that extraction with `--extraction extraction-gaps`. Say so, and say what it costs: one more pass over every paper.

   Read the theories from their saves (`theorize show theories-gaps`, `theorize show theories-gaps-typed`). Cluster them by the gap they close and the explanation they give, as in Theory generation's step 7.

5. **Predictions.** For each kept theory, write `<run>/theories/<id>.md`: the gap it targets, its predictions, and for each prediction the measured quantity, the statistic, the direction, and the threshold (significance and smallest effect that counts). Commit them before opening any data. Do not change them after.

6. **Data and testability.** Start with the person's datasets (see [Datasets from the person](#datasets-from-the-person)). If they leave predictions untested, or the person gave none, Data Search finds more data independent of the corpus: a different cohort, site, instrument, period or method from the studies the theory was built on. Use Data Driven Theory Generation's step 2 to find, describe and measure the data. Then judge each prediction:
   - **testable:** the data has the same quantity, enough cases at the expected effect size, and a positive control that recovers a known effect;
   - **proxy:** the data has a related quantity; test it, and carry the proxy as a caveat;
   - **not testable,** with one reason: *no data*, *underpowered*, or *not identifiable* (the data cannot separate the claim from a rival explanation, or the relation is true by construction).

7. **Tests.** Run exactly the committed test for each testable prediction. A subagent given only the design and the data is the cleanest way. Record effect size, p, n, the code and a figure in `<run>/tests/`. Audit each result with a negative control for an effect, a positive control for a null, and a check for influential points. Give each prediction a verdict from Secondary reproduction: supported, partly supported, opposite effect, rejected, or undecided with its reason.

   AutoDS may run alongside, with the theories' predictions as its `--intent`, to look for findings the committed tests did not ask about. Report its findings as exploratory, never as tests of the theories.

8. **What is missing.** For each prediction that no dataset could decide, and each *thin* or *underpowered null* gap sent here from the check-in, write the study that would decide it, in `<run>/missing.md`:
   - **What to measure:** the quantity, its unit, and how it is measured; the system or population, and the setting.
   - **Design:** observational, intervention or natural experiment, and why it separates the claim from its main rival explanation. Name that rival. An observational design that cannot separate them is not enough; say what would.
   - **Size:** the sample needed to detect the expected effect at conventional power (80 percent, alpha 0.05), with the source of the expected effect size: a paper in the corpus by tag, or the smallest effect that would matter, said to be that. Do not invent an effect size.
   - **Existing data:** whether such data may already exist. Name a repository, cohort or deposit only if a paper in the corpus or a Data Search result points to it; otherwise say it must be collected.
   - **What each result would mean:** which outcome supports the theory, which refutes it, and which leaves it undecided.

   Link each one to the gap it would close. Then ask the person whether they have, or can get, such data. If they give it, it enters at step 6.

9. **Revision (optional).** Feed the verdicts back to Theorizer as the mission statement, as in Secondary reproduction's step 5. Theories that failed are evidence, not noise.

10. **Report.** Under 300 words in the reply; the detail is in the files.
    - **Gap map,** in three lines: the main known, the main gap, the main unknown.
    - **Theories,** one line each: name, gap targeted, verdict.
    - **What the data could not decide,** and the study that would.
    - **Confidence,** as a label, with what might make it wrong.
