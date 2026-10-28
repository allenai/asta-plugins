# Gap-Driven Theory Testing

Map what the literature knows and does not know about a question. Build theories that aim at the gaps. Test each theory on a dataset the papers did not use. For each theory the data cannot test, name the experiment or data that would.

This workflow reuses [Theory generation](theory-generation.md) for the papers and theories, and the verdict rules of [Secondary reproduction](secondary-reproduction.md) for the tests. It adds three things: the gap map, rules for theory scale, and a record of the data each untested theory still needs.

It differs from [Data Driven Theory Generation](data-driven-theory-generation.md) in order. There, experiments run first and the theories explain them. Here, the theories and their predictions are fixed first and the data tests them. A prediction written before the data is seen is a real test. A theory fitted to the data afterwards is not.

## Plan

| Step | Agent | What it does | Configuration |
|---|---|---|---|
| 1 | Paper Finder + local index | Searches the person's local paper index and Paper Finder, and fetches full text | 100 papers in total; the local index, Paper Finder, or both |
| 2 | Theorizer + agent | Extracts findings; the agent writes the gap map (knowns, gaps, unknowns) and checks it against the extractions | extraction `gpt-6-luna` |
| | Check-in | Shows the gap map; the person picks the gaps to target | |
| 3 | Theorizer | Re-plans with the chosen gaps, extracts a second time, and generates theories aimed at the gaps, at the required scale | generation `gpt-6-sol`; gap map as mission statement; a second extraction pass over every paper |
| 4 | Agent | Turns each theory into committed predictions | before any data is opened |
| 5 | Data Search | Takes the person's datasets, finds more if needed, and judges which predictions each can decide | the person's datasets, plus any found during the run |
| 6 | Agent / AutoDS | Runs the committed tests, then audits them | one test per prediction; AutoDS optional, 10 experiments |
| 7 | Agent | Specifies the experiment or data each untested theory needs | |
| 8 | Theorizer (optional) | Revises theories against the verdicts | verdicts as mission statement |

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

- **Keep it out of the theories.** A dataset given before step 4 is not opened, described or shown to Theorizer until the predictions are committed. Only its file names and a one-line summary from the person go into the plan. If the person wants their data to shape the theories, that is [Data Driven Theory Generation](data-driven-theory-generation.md), not this workflow.
- **Check independence.** Compare it with the corpus: same cohort, site, authors, accession or deposit as a paper the theories rest on? If yes, it is not an independent test. Say so, and report its results as consistency checks only.
- **Describe it from its own documentation and the file.** Use Data Driven Theory Generation's step 2. Ask the person for a codebook or README when a column the predictions need has none; do not guess its meaning.
- **A dataset given after the report** re-enters at step 5. The committed predictions stay unchanged. Re-judge testability, run steps 6 and 7 for it, and update the report: which "not testable" items it decided, and which remain.
- **Several datasets.** Test each prediction on each dataset that can decide it, separately. Report agreement across datasets. Do not pool them unless the person asks and the measures are the same.

## Steps

The run directory holds `theory/` (the Theorizer project), `papers.md`, `gaps.md`, `theories/`, `data/`, `tests/` and `report.md`.

1. **Papers.** Run Theory generation's step 1 into `<run>/theory`. Then gather papers from the local index, Paper Finder, or both, as [Papers from a local index](#papers-from-a-local-index) describes. Say how many papers came from each source, out of the target.

2. **Gap map.** Extract with the plan's first schema:

   ```bash
   theorize -p <run>/theory extract
   ```

   No command writes the gap map. You write it, by reading the extractions, into `<run>/gaps.md` with three lists. Every entry cites the papers it rests on by tag.
   - **Known:** a finding reported by at least two independent studies, in agreement. Give the population or system, the effect and its size.
   - **Gap:** a question the papers ask but do not settle. Name its kind:
     - *conflicting:* studies disagree; say which, and what differs between them (population, method, measure);
     - *thin:* one study, a small sample, or no replication;
     - *untested link:* each part is known, but the link between them is assumed, not measured;
     - *boundary:* known in one setting, untested in another (population, scale, time, conditions).
   - **Unknown:** a question the papers raise as open, or one that follows from the knowns and that no paper addresses. Only list an unknown that a paper points to; do not add questions from outside the corpus.

   **Check the map before showing it.** Because it rests on your reading, check it against the run's files:
   - every entry cites at least one paper tag, and every known cites at least two from different studies;
   - every tag appears in `theorize -p <run>/theory show papers`;
   - every entry matches the extraction rows of the papers it cites. A subagent given only `gaps.md` and the extractions is the cleanest check. Correct or drop any entry the rows do not support, and say how many you dropped.

   **Check in and wait.** Show the gap map. The person picks the gaps the theories should aim at. If they asked to run without check-ins, pick the gaps where a test is most likely possible, and say which you picked.

3. **Theories.** Write the chosen gaps into `<run>/mission.md` in the shape below. The first extraction was planned before the gaps were known, so it may not record the variables the gaps need. Plan again with the mission, extract once more with the new schema, and generate from that extraction:

   ```bash
   theorize -p <run>/theory plan "<the question>" --mission-statement "$(cat <run>/mission.md)" --save-as plan-gaps
   theorize -p <run>/theory extract --schema plan-gaps --schema-id schema-gaps --save-as extraction-gaps
   theorize -p <run>/theory theories generate --extraction extraction-gaps --max-data-tokens 750000 --mission-statement "$(cat <run>/mission.md)" --save-as theories-gaps
   theorize -p <run>/theory show theories
   ```

   This is the run's second extraction pass, over every paper. Say so in the plan. Do not run Theory generation's step 3, which would extract a third time. If the person wants more schemas, run Theory generation's steps 4 and 5 after this, adding the mission to every generation.

   The mission, in `<run>/mission.md`:

   ```
   <the question>

   TARGET GAPS FROM THIS RUN'S LITERATURE MAP. Each theory must aim to close at least one
   gap below, and name which. Do not restate a known finding as a theory.

   KNOWN (a theory must stay consistent with these, or say which one it overturns and why):
   - ...
   GAPS TO TARGET:
   - [G1, conflicting] ...
   - [G2, untested link] ...

   SCALE AND SPECIFICITY. Each theory must state:
   - the system or population, and the level it works at (molecule, cell, organism,
     population, ecosystem; or individual, group, institution);
   - the variables, by name, each one something that can be measured;
   - the direction, and the form where possible (threshold, monotone, interaction);
   - the conditions under which it holds, and where it should fail;
   - one prediction that would be false if the theory were wrong.
   A theory too broad to fail ("X influences Y") or so narrow it repeats one study is
   rejected.
   ```

   Then check each theory against the scale rules yourself. Set aside any that fail, and say why. A theory is at the right scale when one study, or one dataset, could decide its prediction, and when deciding it would settle the gap it names.

4. **Predictions.** For each kept theory, write `<run>/theories/<id>.md`: the gap it targets, its predictions, and for each prediction the measured quantity, the statistic, the direction, and the threshold (significance and smallest effect that counts). Commit them before opening any data. Do not change them after.

5. **Data and testability.** Start with the person's datasets (see [Datasets from the person](#datasets-from-the-person)). If they leave predictions untested, or the person gave none, Data Search finds more data independent of the corpus: a different cohort, site, instrument, period or method from the studies the theory was built on. Use Data Driven Theory Generation's step 2 to find, describe and measure the data. Then judge each prediction:
   - **testable:** the data has the same quantity, enough cases at the expected effect size, and a positive control that recovers a known effect;
   - **proxy:** the data has a related quantity; test it, and carry the proxy as a caveat;
   - **not testable,** with one reason: *no data*, *underpowered*, or *not identifiable* (the data cannot separate the claim from a rival explanation, or the relation is true by construction).

6. **Tests.** Run exactly the committed test for each testable prediction. A subagent given only the design and the data is the cleanest way. Record effect size, p, n, the code and a figure in `<run>/tests/`. Audit each result with a negative control for an effect, a positive control for a null, and a check for influential points. Give each prediction a verdict from Secondary reproduction: supported, partly supported, opposite effect, rejected, or undecided with its reason.

   AutoDS may run alongside, with the theories' predictions as its `--intent`, to look for findings the committed tests did not ask about. Report its findings as exploratory, never as tests of the theories.

7. **What is missing.** For each prediction that no dataset could decide, write the experiment or data that would decide it:
   - the quantity to measure, and in what system or population;
   - the design (observational, intervention, natural experiment), and why it identifies the claim;
   - the sample size needed at the expected effect size, with the effect size's source;
   - whether such data may already exist (a named repository or cohort), or must be collected.
   Link each one to the gap it would close. Then ask the person whether they have, or can get, such data. If they give it, it enters at step 5.

8. **Revision (optional).** Feed the verdicts back to Theorizer as the mission statement, as in Secondary reproduction's step 5. Theories that failed are evidence, not noise.

9. **Report.** Under 300 words in the reply; the detail is in the files.
   - **Gap map,** in three lines: the main known, the main gap, the main unknown.
   - **Theories,** one line each: name, gap targeted, verdict.
   - **What the data could not decide,** and the experiment that would.
   - **Confidence,** as a label, with what might make it wrong.
