# Theory generation

Build theories from the literature on a question. Semantic Scholar (`s2`) finds the papers and `asta-papers` fetches their full text. Theorizer extracts findings from them and generates theories, then asks the papers which variables the first extraction missed and runs one more pass for each new schema. Every pass adds its theories to the same theory store.

Semantic Scholar is the source unless the person points you at papers of their own -- a folder, files, a glob. When they do, [Bring Your Own Papers](#bring-your-own-papers) replaces the search in step 2 and the rest of the workflow is unchanged.

## Setup

Before the plan, check that Theorizer is installed and ready, and the paper tools of [S2 to asta-papers to Theorizer](s2-papers.md#setup):

```bash
uv tool install --upgrade --python 3.13 asta-theorizer --with "pymupdf4llm<2"
theorize doctor
command -v s2 asta-papers
```

`--upgrade` replaces an older `theorize` already on PATH; without it the run gets whatever is there. If `theorize --version` already reports the version the person or the environment asks for (for example, a newer build than PyPI's, provided for testing), skip the install line, which would replace it with PyPI's. Both pins matter. Without `--python`, uv builds on the newest Python it finds, where one dependency has no prebuilt package and the install fails part-way through compiling it. And `pymupdf4llm` 2.0 on PyPI is an empty package, so without that pin, PDFs are imported as metadata with no text.

`doctor` exits non-zero on anything that would stop a run, and says how to fix it. A missing key is the common one, and this is the fix that needs no restart -- Theorizer reads the file on the next command:

```bash
mkdir -p ~/.config/asta && echo '{"openai": "..."}' > ~/.config/asta/api_keys.donotcommit.json   # or "anthropic"
```

That location works from any directory and sits outside any repository; a copy in the working directory, or `--key-dir DIR`, is read first if they want one per project. They can also put `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in their shell profile, which lasts across runs but only reaches a session started after it. Never ask for the key in chat, where it would be kept in the transcript.

## Plan

Show the person this table, with the values for their question (the paper target, for one). Quote their question in step 1 exactly as Theorizer will get it, so they see what it will work from. The commands under Steps say which models and settings each step uses.

With the person's own papers, step 1 plans the extraction schema only and step 2 reads `| 2 | Theorizer | Imports their N papers from <their folder>. No search. |`. Count the files first, so N is real.

| Step | Agent | What it does |
|---|---|---|
| 1 | Theorizer | Plans the paper search and extraction schema for "<their question>" |
| 2 | Semantic Scholar | Finds 100 papers with `s2` and fetches their full text with `asta-papers` |
| 3 | Theorizer | Extracts findings and generates the first theories |
| | Check-in | Shows you the first theories; you choose 4a or 4b |
| 4a | Theorizer | Refines the theories with your direction, from the same findings |
| 4b | Theorizer | Discovers variables the first pass missed, then generates theories for each new schema |

After the table, write this word for word, filling in only the two examples of a focus from their question. The examples are suggestions, so use only what the person picks.

> You can make the theories more specific:
>
> - **Focus:** A particular mechanism or population, e.g. <two from their question>?
> - **Theory shape:** A threshold equation, an "if–then" rule, or another form?
> - **Papers:** Any required papers, or papers that should form the entire corpus?

Leave out any of the three they have already settled: someone who gave you a folder has answered the papers question.

If the person asks you to run the workflow autonomously, or to choose for them, use your discretion: pick a focus and a theory shape that suit the research context, and say what you picked.

Shape is worth asking about: Theorizer spots laws far more readily when it is told their shape (a production rule such as acids + alkalis -> salts + water, an IF ... THEN law, a quantitative relation) than when asked for theories about a topic.

## The run's page

When the project is a workspace site (the `workspace` skill), the run's files go in `.asta/flows/<NNNN>-theory-generation/` (the run layout in run-workflow's skill), and the run has one page, `pages/<NNNN>-theory-generation.qmd`, with the same NNNN:

```
.asta/flows/<NNNN>-theory-generation/    this is <run>
  workflow.yaml, README.md                the run's record
  workflow.mmd                            the run's diagram, when you draw one
  theory/                                 the Theorizer project (full text, prompts, logs; no page reads it)
  data/                                   theorizer.json and papers.json, written by scripts/theorizer-site-data
pages/<NNNN>-theory-generation.qmd       the run's page: the diagram, the papers, the theories
```

To start the page, copy `templates/page.qmd` to `pages/<NNNN>-theory-generation.qmd` and replace `{{RUN}}` with the run's folder name (`<NNNN>-theory-generation`); its front matter is the title (the workflow's name) and nothing else. The site's sidebar lists it with the other workflow pages, in run order. The page is widgets only: add no ledger, prose or tables to it. After papers are fetched, after every extraction and after every generation, write the data and render, even when those steps run in one turn:

```bash
python3 <this folder>/scripts/theorizer-site-data <run>/theory <run>/data/theorizer.json --bib references.bib
quarto render      # or `make render` where the workspace Makefile is set up
```

When the run's store holds documents collected by hand whose metadata was checked after they were imported (a collection's `metadata.json`: CSL-style records keyed by the store's `id`), add `--metadata <that file>`: its title, authors, year, venue and DOI replace the store's on the pages.

The site is where you maintain the notes for the human collaborator, as the `workspace` skill's "In a hosted sandbox" section says. For this workflow:

- **Front page** (the project's `index.qmd`, started from the `workspace` skill's `assets/cover.qmd`): Mission, Abstract, Findings, Null results, Next steps.
- **Caveats:** what you tell the person about how far to trust the results goes on the front page under Findings, in the same words. A theory's text cannot be edited, so name the theory whose figures overstate their evidence.
- **Names:** call a theory by its name on the theory page, in chat as on the site.
- **The workflow diagram:** when you draw the run's plan or progress as a diagram, save its Mermaid source as `<run>/workflow.mmd`, left to right (`flowchart LR`), and keep it current as steps finish. The `{{< asta-workflow >}}` line in the run's page shows it; without the file the page shows nothing there.

The pages need the `asta-pages` extension from the `workspace` skill's assets (`make workspace-assets` fetches it when a page uses it). Quarto renders every `.md` and `.qmd` under the site, so keep a person's own markdown papers in a folder whose name starts with `_`, which Quarto skips.

## Steps

`<run>/theory` is the Theorizer project. Every step saves into it, so the passes share one corpus and one theory store.

1. **Plan.** Theorizer plans the run from the question: a paper search query, an extraction query and a first schema:

   ```bash
   theorize -p <run>/theory init
   theorize -p <run>/theory plan "<the question>"
   ```

   `init` prints the two models the project uses: `gpt-6-sol` for the once-per-run stages (plan, schemas, theories) and `gpt-6-luna` for the per-paper ones (extract, discover, import), whatever key it finds. `THEORIZER_MODEL` and `THEORIZER_EXTRACTION_MODEL` override them when set. Name that pair in the plan. Pass `--model` and `--extraction-model` only when the person asks for something else.

   Pass their question as they wrote it, leaving out only instructions for the run itself (how many papers, which models). Add only what they gave: a shape goes into the question ("Find IF ... THEN laws for ..."), since the plan's request is the theory query the generator reads, and a focus goes in as `--mission-statement`, so it shapes the search query and the schema. A workflow that adds a mission statement after the papers are in runs `plan` again with it before extracting.

2. **Papers.** If they pointed you at their own papers, import them, search for nothing, and go on to step 3 -- see [Bring Your Own Papers](#bring-your-own-papers). Otherwise collect and fetch them with [S2 to asta-papers to Theorizer](s2-papers.md): `s2` searches with the plan's search query, `asta-papers store` fetches the full text of the first `<papers>` in its order into `<run>/store.json`, and `theorize papers import <run>/store.json` brings the store into the project. Follow that file for the commands, for following references and for topping up. Do not use `theorize papers search` or `theorize papers fetch` here.

   If fewer than the target come back with full text, top up from the saved search or search again from another angle, until the target is reached. If the target is still not reached, go on with the papers that have full text. Theorizer extracts from full text only, so do not add abstract-only papers some other way. When you report the theories, say how many papers they rest on, out of the target, how many were tried, and why the others have no full text.

   If the person gave papers, `papers import` adds them: see [Bring Your Own Papers](#bring-your-own-papers). When they say their papers are the corpus, import them and search for none.

3. **First pass.** Theorizer extracts from every paper with the plan's schema, and generates theories:

   ```bash
   theorize -p <run>/theory extract
   theorize -p <run>/theory theories generate --max-data-tokens 750000
   theorize -p <run>/theory show theories
   ```

   **Check the extraction before you generate.** `extract` lists each paper whose model call gave up, with the reason (`timeout`, `error`, `prompt_too_long`, `unreadable_answer`) and the limit it had; rerunning the same command retries only those papers, and `--llm-timeout SECONDS` gives them longer. A paper the model read and found nothing in is a result, not a failure. If papers failed or have no findings, say which and why, and offer to extract the failed ones again before generating; do not generate from a fraction of the papers without telling the person. Name the extraction model in the plan.

   `--max-data-tokens` is how much evidence one generation call reads before it subsamples; 750000 fits either model pair. With 200 papers or more, add `--objective attribution-batched` to every generation in the run: it reads the evidence that does not fit in further batches instead of leaving it out. Say so in the plan.

   **If a generation produces no theories or stops with an error,** `theorize` names any model call that gave up, with its limit and how to rerun (`--llm-timeout`). A call the model's safety filter stopped answers with nothing; run the same command once more (a `plan` call stopped the same way usually passes too), and if it fails again, tell the person which call failed. Theorizer stays on GPT: do not move it to a Claude model.

   **Check in and wait.** Variable discovery and the schema passes cost several times the first pass, so stop here. Go straight on to 4b only if the person explicitly asked, when agreeing the plan, to run without the check-in. List the first theories, one line each, and offer the two ways on from the plan:

   - **4a, refine the theories.** Generate again from the same findings, with the person's direction (a focus, a mechanism, a kind of explanation, theories to set aside) in the mission statement. Nothing is extracted again.

     ```bash
     theorize -p <run>/theory theories generate --max-data-tokens 750000 --mission-statement "<the question, then their direction>" --save-as theories-refined-<n>
     ```

     Report and publish it as in step 6, then check in again: they can refine again, go on to 4b, or stop.
   - **4b, discover new variables:** steps 4 and 5.

4. **Missed variables.** Ask each paper which variables are worth extracting beyond the ones the first schema records, then design new schemas from the answers. List the first schema's fields with `theorize -p <run>/theory show plan`, and name them in the context:

   ```bash
   theorize -p <run>/theory discover --context "The first extraction already records: <its field names>. Propose variables it does not capture."
   theorize -p <run>/theory schemas from-discovery
   ```

   It prints the new schemas as `schemas#0`, `schemas#1` and so on, usually 2 to 4 of them. Each has its own extraction query. `theorize -p <run>/theory load schemas` prints them in full.

5. **Schema passes.** For each schema, extract with it, then generate from that extraction. Number the schema IDs on from the first pass's `schema-1`, so each theory's evidence stays with its own schema:

   ```bash
   theorize -p <run>/theory extract --schema schemas#0 --schema-id schema-2 --save-as extraction-schema-2
   theorize -p <run>/theory theories generate --extraction extraction-schema-2 --max-data-tokens 750000 --save-as theories-schema-2
   ```

   Then `schemas#1` as `schema-3`, and so on. The passes are independent: run them one after another or side by side.

6. **Updates.** After every generation, tell the person what the pass produced. When the project is a workspace site, write the run's data and render it ([The run's page](#the-runs-page)). If you have a tool for publishing artifacts, publish the theories with it too.

7. **Summary.** End the run by clustering the theories from every pass by the explanation they give. Theories from different schemas often restate each other; a cluster that several schemas reached rests on more of the evidence than one only a single schema produced. For each cluster, say what it is about in plain language and then in a few technical sentences, and why the person should care. Weigh the clusters by similarity, impact and novelty, and point the person to the ones they are likely to find most interesting, so they can find them quickly without reading every theory. Cluster even when the person asked for a theory shape: state each cluster's laws in that shape, in its technical sentences.

## Bring Your Own Papers

```bash
theorize -p <run>/theory papers import <their folder>      # every .md, .txt and .pdf under it
theorize -p <run>/theory papers import <files or a glob>
theorize -p <run>/theory show papers
```

Markdown is read as it is. PDFs are converted on import; add `--ocr mistral` for scanned PDFs when `MISTRAL_API_KEY` is set. Figures are not read: a markdown file that refers to them as image tags hands those tags over as text.

Import spends one small LLM call per paper on metadata, and a brought corpus has no paper target to bound it. Say the count when you show the plan, and say that step 4b extracts over every paper again for each schema it produces.
