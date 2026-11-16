# Theory generation

Build theories from the literature on a question. Theorizer plans a search and an extraction schema, the papers are found and fetched, and Theorizer extracts findings from them and generates theories. Then it asks the papers which variables the first extraction missed, and runs one more pass for each new schema. Every pass adds to the same theory store.

The papers come from Semantic Scholar unless the person points you at their own: a folder, files or a glob. Then those replace the search, and the rest is the same.

How to run each step is in the `generate-theories` skill.

## Plan

Quote their question in step 1 exactly as Theorizer will get it. With their own papers, step 1 plans the schema only, and step 2 reads `| 2 | Theorizer | Imports their N papers from <their folder>. No search. |`, with N counted.

| Step | Agent | What it does |
|---|---|---|
| 1 | Theorizer | Plans the paper search and extraction schema for "<their question>" |
| 2 | Semantic Scholar | Finds 100 papers and fetches their full text |
| 3 | Theorizer | Extracts findings and generates the first theories |
| | Check-in | Shows you the first theories; you choose 4a or 4b |
| 4a | Theorizer | Refines the theories with your direction, from the same findings |
| 4b | Theorizer | Discovers variables the first pass missed, then generates theories for each new schema |

After the table, write this word for word, filling in only the two examples of a focus from their question. Leave out any they've already settled.

> You can make the theories more specific:
>
> - **Focus:** A particular mechanism or population, e.g. <two from their question>?
> - **Theory shape:** A threshold equation, an "if–then" rule, or another form?
> - **Papers:** Any required papers, or papers that should form the entire corpus?

If they ask you to choose, pick a focus and a shape that suit the question, and say what you picked.

## Steps

1. **Plan,** from their question. A shape goes into the question; a focus goes in as the mission statement.
2. **Papers,** to the target, full text only. Top up if too few come back with full text, then go on with what there is and say so.
3. **First pass:** extract, check the extraction, generate.
4. **Check in and wait.** The next steps cost several times the first. List the first theories, one line each, and offer:
   - **4a, refine:** generate again from the same findings, with their direction in the mission statement. Then check in again.
   - **4b, discover:** ask the papers which variables the first schema missed, then extract and generate once per new schema.

   Go straight to 4b only if they asked for no check-in when agreeing the plan.
5. **Updates.** After every generation, tell them what the pass produced, and update the run's page.
6. **Summary:** the theories from every pass, clustered by the explanation they give, even when they asked for a shape.

## The run's page

```
.asta/flows/<NNNN>-theory-generation/    <run>
  workflow.yaml, README.md, workflow.mmd
  theory/                                 the Theorizer project
  data/                                   theorizer.json and papers.json
pages/<NNNN>-theory-generation.qmd       the diagram, the papers, the theories
```

Copy `templates/page.qmd` to the page and replace `{{RUN}}` with the run's folder name. After papers are fetched, after every extraction and after every generation, write the data and render:

```bash
python3 <this folder>/scripts/theorizer-site-data <run>/theory <run>/data/theorizer.json --bib references.bib
quarto render      # or `make render`
```

- **References.** `--bib` adds an entry per paper to the site's `references.bib`, keyed `s2-<corpus id>`. For papers collected by hand with checked metadata (a `metadata.json` of CSL records keyed by the store's `id`), add `--metadata <that file>`.
- **Diagram.** Keep the run's plan as Mermaid in `<run>/workflow.mmd` (`flowchart LR`), current as steps finish.
- **The person's markdown papers** go in a folder whose name starts with `_`, which Quarto skips.
