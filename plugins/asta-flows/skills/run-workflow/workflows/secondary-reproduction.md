# Secondary reproduction

Reproduce an existing AutoDS run's hypotheses on independent data, then build literature-grounded theories from the verdicts with Theorizer. Only independent data counts. The run's own dataset is never reused.

The papers and theories are [Theory generation](theory-generation.md)'s steps. This file says what this workflow adds to them: a search per theme, and the verdicts as Theorizer's mission.

## Plan

Show the person this table, with the values for their run. Everything not in it runs on the command's own default.

| Step | Agent | What it does | Configuration |
|---|---|---|---|
| 1 | AutoDS | Selects the hypotheses to reproduce from the run | the directory the person gives, or a new run of 10 experiments on their data with model `openai/gpt-6-luna`; every surprising hypothesis, plus the N highest and N lowest by posterior belief, N = 10 |
| 2 | Paper Finder | Gathers the literature on the hypotheses' themes | 5 themes plus the run's intent; 20 papers per theme (`papers fetch --top`) |
| 3 | Data Search | Finds independent data for each hypothesis | chosen during the run |
| 4 | Reproduce | Re-runs each hypothesis's test on the new data | one test per hypothesis |
| 5 | Theorizer | Builds theories that must explain the verdicts; then a pass for each schema variable discovery designs | extraction `gpt-6-luna`, generation `gpt-6-sol`, objective novelty; usually 2 to 4 more schemas |

## Verdicts

A reproduction is judged on three separate axes:

- **Faithfulness.** Is the independent test the same quantity, a proxy, or a substitution? A proxy is a caveat carried with the verdict, never a verdict. A substitution is not a reproduction and is not run.
- **Decidability.** Could the test decide? If not, the verdict is **undecided**, with one reason:
  - **underpowered**: it ran, but had too few cases to detect the source effect;
  - **no data**: no independent data covered it;
  - **not identifiable**: the construct cannot isolate the claim, for example because it is true by construction.
- **Outcome**, for a test that could decide:
  - **supported**: the threshold was met in the hypothesized direction;
  - **partly supported**: one committed component met it;
  - **opposite effect**: significant in the other direction, which is never support;
  - **rejected**: a null with adequate power and a passing positive control.

A favorable estimate that misses the threshold is undecided, not support. Read the verdict from the numbers, not from the prose.

## Steps

1. **Selection.** From the run's `mcts_node_*.json` files, take every surprising node, plus the N highest and N lowest by posterior mean, without duplicates. Each becomes one hypothesis. Copy its hypothesis text verbatim, and keep its plan, code, prior and posterior means, and belief change. Do not group, merge or reword.

2. **Literature,** alongside step 3. Cluster the hypotheses into themes and add one for the run's overall intent, taken from its metadata. Run [Theory generation](theory-generation.md)'s step 1 with one search per theme into the same project, in place of the single search on the question:

   ```bash
   theorize -p <run>/theory init --model gpt-6-sol --extraction-model gpt-6-luna
   theorize -p <run>/theory papers search "<theme>" --save-as theme-1
   theorize -p <run>/theory papers fetch --top <n> --from theme-1
   ```

3. **Independent data.** Data Search finds data for every hypothesis that differs from the source in a named way: instrument, cohort, region, method or time. Before any test, judge whether the data can decide each hypothesis: whether it is testable, the usable sample and event counts, and whether that is enough at the source effect size. Run one positive control that recovers a known effect on this data, and report its numbers. Every hypothesis ends covered by a dataset or recorded as a gap.

4. **Reproduction,** for each hypothesis with covering data.
   - **Design.** Adapt the AutoDS experiment; do not design a new one. Keep the statistic, the direction and the decision rule, and change only what the new data requires. Vary one independence axis per test, so a failure to reproduce can be traced to it. Judge faithfulness. Commit the test and its threshold, both significance and minimum effect, before running anything.
   - **Run.** Run exactly the committed test, without looking at the source result. A separate subagent given only the design and the data is the cleanest way. Record the effect size, p, n, the code and a figure. If the test cannot run, record that and why.
   - **Audit.** Try to refute the result. Use a control suited to it: a negative control for an effect, a positive control for a null, a block permutation for clustered or time data. Check sensitivity to influential points. Rule out a setup artifact before calling a failure to reproduce. Set the verdict. Flag the source finding as an error only when confident the run's own result is wrong.

5. **Theories.** Reconstruct what the run's user set out to learn, from its stated intent and dataset descriptions, and use it as the question. Theorizer reads only the papers, so the verdicts go in as its mission statement. Run [Theory generation](theory-generation.md)'s steps 2 to 6, adding the mission to the plan, and the mission and `--objective novelty` to every generation:

   ```bash
   theorize -p <run>/theory plan "<the question>" --mission-statement "$(cat <run>/mission.md)"
   theorize -p <run>/theory theories generate --max-data-tokens 750000 --mission-statement "$(cat <run>/mission.md)" --objective novelty
   theorize -p <run>/theory theories generate --extraction extraction-schema-2 --max-data-tokens 750000 --mission-statement "$(cat <run>/mission.md)" --objective novelty --save-as theories-schema-2
   ```

   The mission, in `<run>/mission.md`:

   ```
   <the question>

   REPRODUCTION OF AN AUTODS RUN ON INDEPENDENT DATA (<n> hypotheses tested on <the datasets>).
   The theories you form must account for these verdicts, and each should explain several
   hypotheses. A hypothesis that did not reproduce is conflicting evidence, not noise. Do not
   restate the hypotheses as theories. Explain them, and say which ones each theory covers.

   REPRODUCED:
   - <the hypothesis, verbatim>
       source: <the AutoDS effect>   independent: <the effect, p and n on the new data>
   NOT REPRODUCED (opposite effect, or rejected):
   - ...
   UNDECIDED, with the reason:
   - ...
   ```

   Drop a hypothesis only when its source finding was flagged as an error. Report the hypotheses each theory leaves unexplained.

6. **Findings.**
   - **The front page** is for a reader outside the field. Orient them to the domain without giving away the discovery. Say what the study found, then separate what the field already knew from what this work adds. Expand every acronym, and use no tool names and no statistics. End with a short list of key findings, each tagged as reproduced, proposed or refuted.
   - **The scientist's synthesis** leads with the honest bottom line, even when it is that the data could not decide most of it. Cover what held up and what it means, what the work adds against the literature, and why it could not answer more. End with the specific data or single test that would settle each open question.
