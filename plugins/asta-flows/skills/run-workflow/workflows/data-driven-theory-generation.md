# Data Driven Theory Generation

Build theories that explain the question, grounded in the literature and in experiments this run computes on real data. The experiments are the only evidence in the run that was computed rather than read, so the theories must answer to them.

The papers and theories are [Theory generation](theory-generation.md)'s steps. This file says what this workflow adds to them: the data, the experiments, and the mission that carries the experiments to Theorizer.

## Data and angle

Before the plan, ask the person two things in one short message, then wait for the answer:

- **Data.** Do they have a dataset, or one in mind (a cohort, a portal, a paper's deposit)? Or should Data Search find one?
- **Angle.** Should the run focus on one part of the question, a mechanism, a subgroup or a kind of finding? Say which parts of the question AutoDS can test on data and which rest on the literature, so they can choose where the experiments go.

Offer what you would pick if they have no preference, in one line each. Do not search, download or run anything before they answer. Their answers set the plan: the data step uses what they named, and the angle goes into AutoDS's `--intent` and Theorizer's question.

## Plan

Show the person this table, with the values for their question. Everything not in it runs on the command's own default.

| Step | Agent | What it does | Configuration |
|---|---|---|---|
| 1 | Paper Finder | Searches for the question, fetches the top papers' full text, and fills any gap to the target | 100 papers (`papers fetch --top`) |
| 2 | Data Search | Finds a dataset the question can be tested on | the person's data, or chosen during the run |
| 3 | AutoDS | Runs experiments on the data | 10 experiments (`--n_experiments`), model `openai/gpt-6-luna` |
| 4 | Theorizer | Extracts findings from the papers and builds theories that must explain the experiments; then a pass for each schema variable discovery designs | extraction `gpt-6-luna`, generation `gpt-6-sol`; usually 2 to 4 more schemas |

AutoDS model names carry their provider (`openai/`), and its model, vision model and belief model are all the AutoDS model. Theorizer's names have none.

## Theorizer's mission statement

Theorizer reads the papers and nothing else. Left with the bare question, it ignores the experiments this run just computed. So the findings go in as its mission statement (`--mission-statement`), in this shape:

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

- **A finding** is an experiment that ran and left an analysis or a belief change. Surprising ones come first, because they are what a theory owes an explanation.
- **Mark a suspected artifact** in the list rather than dropping it silently.
- **Keep each hypothesis and analysis in AutoDS's own words,** trimmed for length only.
- **Never leave out the limits.** One run's theory explained a correlation of r=0.147 without mentioning that it fell to 0.059 once proliferation was adjusted for. That caveat was in the search's notes, but not in the mission.

## Steps

The run directory holds three things: `theory/` is the Theorizer project, `data/` holds the datasets, and `autods/` holds the search.

1. **Papers.** Run [Theory generation](theory-generation.md)'s step 1 into `<run>/theory`. The papers also give Data Search its leads.

2. **Data.** Data Search finds one dataset the question can be tested on, and writes the description AutoDS reads. No command does this yet. If the person named data, use it, and only describe it.
   - **Find it** from the deposits the papers name: look in `<run>/theory/paperstore.json` for data-availability statements, repository DOIs (Dryad, Zenodo, figshare) and accessions. Search the portals only if the papers name none that fits. Take one dataset that loads and tests in minutes, and download it into `<run>/data/`.
   - **Describe it from its own documentation:** the portal's record page, then a README or codebook shipped with the files. Read the primary paper's methods only when a column the question needs is still undescribed. Use the source's words for what the data are; where it says "resting or basal", do not write "basal, thermoneutral". A column no source describes is said to be undescribed, not guessed at.
   - **Measure it from the file,** with pandas: the rows left after every restriction the question imposes, and for each column the question uses, how many values are present, the range or the levels, and how missing values are written.
   - **Write down the cautions you observe in the bytes,** each with numbers a reader can check against the file:
     - sentinel values and unit traps;
     - two columns that look alike but are not the same quantity, and which one a measurement is paired with;
     - a quantity derived from another, so that relating the two is true by construction;
     - rows that are not independent (shared lineage, site or subject), and a group that dominates the sample;
     - a few rows at an extreme with high leverage.
   - **Say what the data are, never what they show.** The description carries no result: no fitted relationship between the question's variables, no expected value, no range the literature reports, no hypothesis. AutoDS told what to find tends to find it.
   - Save it as `<run>/data/<file>.description.md`, in this order: what the dataset is and what one row is; the subset and its size; each column the question uses, with its meaning, units and measured profile; the cautions.

3. **Experiments.** AutoDS searches over experiments on the data. Run it in the background:

   ```bash
   auto-discovery <run>/data/<file> \
     --intent "<the question>" \
     --dataset_description "$(cat <run>/data/<file>.description.md)" \
     --n_experiments <experiments> \
     --model <model> --vision_model <model> --belief_model <model> \
     --out_dir <run>/autods
   ```

   Give one `--dataset_description` per file, in the same order as the files. Each experiment lands as `<run>/autods/mcts_node_*.json`, with its hypothesis, plan, code, analysis and belief change.
   - While it runs, say so when several experiments fail the same way, rather than letting the budget drain.
   - When it ends, read every node. For each large belief change, ask what caused it. A bug, a leak or a quantity true by construction swings belief hard and means nothing; mark it as an artifact. A confirmation of the prior is a real, low-surprise result.
   - Say why the search stopped, and how many experiments ran and failed. A partial search, described as partial, is still usable.

4. **Theories,** once AutoDS has ended. Write the mission from its findings, in the shape above, to `<run>/mission.md`. Then run [Theory generation](theory-generation.md)'s steps 2 to 6, adding the mission to the plan and to every generation:

   ```bash
   theorize -p <run>/theory plan "<the question>" --mission-statement "$(cat <run>/mission.md)"
   theorize -p <run>/theory theories generate --max-data-tokens 750000 --mission-statement "$(cat <run>/mission.md)"
   theorize -p <run>/theory theories generate --extraction extraction-schema-2 --max-data-tokens 750000 --mission-statement "$(cat <run>/mission.md)" --save-as theories-schema-2
   ```

   - Read the theories against the findings. Name any surprising result that no theory explains. That gap is the most useful sentence in the report.
   - If AutoDS produced no findings, say the theories rest on the literature alone. That is a weaker claim.

5. **Report.** The artifacts hold the detail. The reply is short, under 200 words:
   - **Answer,** in two or three sentences.
   - **Theories,** one line each: its name, and the findings it explains.
   - **Gap:** the surprising result no theory explains, in one line.
   - **Confidence,** as a label (very high, high, low, very low), with what might make it wrong.
   - **Next:** the one test or dataset that would settle the open question.

   Leave out the funnel, the data's provenance and each experiment's numbers unless the person asks. They are in the artifacts.
