# Secondary reproduction

Reproduce an AutoDS run's hypotheses on independent data, then build literature-grounded theories from the verdicts with Theorizer. Only independent data counts. The run's own dataset is never reused.

The papers and theories are [Theory generation](../theory-generation/README.md)'s steps. This adds a search per theme, the reproductions, and the verdicts as Theorizer's mission.

## Plan

| Step | Agent | What it does | Configuration |
|---|---|---|---|
| 1 | AutoDS | Selects the hypotheses to reproduce from the run | the run the person gives, or a new run of 10 experiments on their data; every surprising hypothesis, plus the N highest and N lowest by posterior belief, N = 10 |
| 2 | Semantic Scholar | Gathers the literature on the hypotheses' themes | 5 themes plus the run's intent; 20 papers per theme |
| 3 | Data Search | Finds independent data for each hypothesis | chosen during the run |
| 4 | Reproduce | Re-runs each hypothesis's test on the new data | one test per hypothesis |
| 5 | Theorizer | Builds theories that must explain the verdicts, then a pass for each new schema | usually 2 to 4 more schemas |

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

1. **Selection.** From the run's experiments (either file kind: the `autodiscovery` skill's "The run's files"), take every surprising one, plus the N highest and N lowest by posterior mean, without duplicates, skipping any without a hypothesis. Each becomes one hypothesis: copy its text verbatim, and keep its plan, code, prior and posterior means, and belief change. Don't group, merge or reword. If the beliefs barely vary, say so, and break ties by a rule fixed in advance, such as experiment order. A run of 2N experiments or fewer is selected whole.

   When a hypothesis is the experiment the run was seeded from, give its test an id of its own and record it at the top of the selection file as `"seed": {"test_id": "<id>", "experiment": <the source run's experiment number>}`, so the site links "Experiment N" to that test.
2. **Literature,** alongside step 3. Cluster the hypotheses into themes, add one for the run's overall intent, and search once per theme into one project and one store.
3. **Independent data.** Data that differs from the source in a named way: instrument, cohort, region, method or time. Before any test, judge whether it can decide each hypothesis: testable or not, the usable sample and event counts, and whether that's enough at the source's effect size. Run one positive control that recovers a known effect on this data, and report it. Every hypothesis ends covered by a dataset or recorded as a gap.
4. **Reproduction,** for each covered hypothesis.
   - **Design.** Adapt the AutoDS experiment; don't design a new one. Keep the statistic, the direction and the decision rule, and change only what the new data requires. Vary one independence axis per test, so a failure can be traced to it. Commit the test and its threshold (significance and minimum effect) before running anything.
   - **Run** exactly the committed test, without looking at the source result. A separate subagent given only the design and the data is the cleanest way; where there are no subagents, a headless agent process (such as `claude -p`) in a folder holding only those. Record the effect size, p, n, the code and a figure.
   - **Audit.** Try to refute it: a negative control for an effect, a positive control for a null, a block permutation for clustered or time data, and a check for influential points. Rule out a setup artifact before calling a failure to reproduce. Flag the source finding as an error only when confident it's wrong.
5. **Theories.** Reconstruct what the run's user set out to learn, from its intent and dataset descriptions, and use it as the question. The verdicts go in as the mission statement, then Theory generation's steps 3 to 6:

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
6. **Calibration.** A table of each reproduced hypothesis's selection group, belief change (signed: posterior minus prior) and verdict, and how often each group reproduced.
7. **Report:** the workspace's cover (`index.qmd`), for a reader outside the field. Orient them without giving away the discovery, say what held up, and separate what the field already knew from what this adds. Lead with the honest bottom line, even when it's that the data couldn't decide most of it. Each finding is tagged reproduced, proposed or refuted. Next steps name the data or single test that would settle each open question.
