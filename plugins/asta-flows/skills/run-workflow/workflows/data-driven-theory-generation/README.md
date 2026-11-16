# Data Driven Theory Generation

Build theories that explain the question, grounded in the literature and in experiments this run computes on real data. The experiments are the only evidence in the run that was computed rather than read, so the theories must answer to them.

The papers and theories are [Theory generation](../theory-generation/README.md)'s steps. This adds the data, the experiments, and the mission that carries the experiments to Theorizer.

## Plan

| Step | Agent | What it does | Configuration |
|---|---|---|---|
| 1 | Semantic Scholar | Finds the papers on the question and fetches their full text | 100 papers |
| 2 | Data Search | Finds a dataset the question can be tested on | the person's data, or chosen during the run |
| 3 | AutoDS | Runs experiments on the data | 10 experiments |
| 4 | Theorizer | Extracts findings and builds theories that must explain the experiments, then a pass for each new schema | usually 2 to 4 more schemas |

Before the next part, say in one sentence which parts of the question AutoDS can test on data and which rest on the literature. Then write this word for word, filling in only the two examples:

> You can make the run more specific:
>
> - **Data:** A dataset you have or have in mind, such as a cohort, a portal or a paper's deposit?
> - **Focus:** A particular mechanism, population or kind of finding, e.g. <two from their question>?
>
> By default, Data Search finds a dataset during the run, and Theorizer gets your question as you wrote it.

A focus goes into AutoDS's prompt and Theorizer's question.

## Steps

1. **Papers,** as Theory generation's steps 1 and 2. They also give Data Search its leads.
2. **Data.** If the person named data, use it. Otherwise look first in the deposits the papers name (data-availability statements, repository DOIs, accessions), and search portals only if none fits. Take one dataset that loads and tests in minutes, and describe it.
3. **Experiments.** AutoDS on the data. When it ends, read every experiment, mark the artifacts, and say why it stopped.
4. **Theories.** Write the findings into Theorizer's mission statement, then run Theory generation's steps 3 to 6 with it:

   ```
   <the question>

   EMPIRICAL FINDINGS FROM THIS RUN'S OWN EXPERIMENTS, computed by AutoDS on <the datasets>
   (<n> experiments, <k> of them surprising). The theories you form must account for them: a
   mechanism that cannot explain a finding below is wrong for this data, however well it reads
   against the literature. Do not restate the findings as theories. Explain them, and say which
   findings each theory covers.

   SURPRISING:
   - <the experiment's hypothesis>
       found: <its analysis, with the numbers>
       belief <prior mean> to <posterior mean>

   OTHER FINDINGS:
   - ...

   WHAT THE SEARCH COULD NOT SETTLE:
   - <the caveats: a confound, an adjustment that weakened a result, a question left open>
   ```

   Keep each hypothesis and analysis in AutoDS's own words, trimmed only for length. Mark a suspected artifact rather than dropping it. Never leave out the limits: one run's theory explained a correlation of r = 0.147 without saying it fell to 0.059 once proliferation was adjusted for.
5. **Report:** the workspace's cover (`index.qmd`). Under Findings, read the theories against the experiments and name any surprising result no theory explains; that gap is the most useful sentence on the page. If AutoDS found nothing, say the theories rest on the literature alone, which is a weaker claim.
