# Theory generation

Build theories from the literature on a question. Paper Finder gathers the papers. Theorizer extracts findings from them and generates theories, then asks the papers which variables the first extraction missed and runs one more pass for each new schema. Every pass adds its theories to the same theory store.

Paper Finder is the source unless the person points you at papers of their own -- a folder, files, a glob. When they do, [Bring Your Own Papers](#bring-your-own-papers) replaces the search in step 2 and the rest of the workflow is unchanged.

## Setup

Before the plan, check that Theorizer is installed and ready:

```bash
uv tool install --upgrade asta-theorizer
theorize doctor
```

`--upgrade` replaces an older `theorize` already on PATH; without it the run gets whatever is there. `doctor` exits non-zero on anything that would stop a run, and says how to fix it: pass that on verbatim before going further. Do not improvise a fix of your own for a missing key -- in particular, never offer to run an `export` in this session (the next command will not see it) and never ask for the key in chat, where it would be kept in the transcript.

## Plan

Show the person this table, with the values for their question (the paper target, for one). Quote their question in step 1 exactly as Theorizer will get it, so they see what it will work from. The commands under Steps say which models and settings each step uses.

With the person's own papers, step 1 plans the extraction schema only and step 2 reads `| 2 | Theorizer | Imports their N papers from <their folder>. No search. |`. Count the files first, so N is real.

| Step | Agent | What it does |
|---|---|---|
| 1 | Theorizer | Plans the paper search and extraction schema for "<their question>" |
| 2 | Paper Finder | Finds 100 papers and fetches their full text |
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

## Steps

`<run>/theory` is the Theorizer project. Every step saves into it, so the passes share one corpus and one theory store.

1. **Plan.** Theorizer plans the run from the question: a paper search query, an extraction query and a first schema:

   ```bash
   theorize -p <run>/theory init --model gpt-6-sol --extraction-model gpt-6-luna
   theorize -p <run>/theory plan "<the question>"
   ```

   Pass their question as they wrote it, leaving out only instructions for the run itself (how many papers, which models). Add only what they gave: a shape goes into the question ("Find IF ... THEN laws for ..."), since the plan's request is the theory query the generator reads, and a focus goes in as `--mission-statement`, so it shapes the search query and the schema. A workflow that adds a mission statement after the papers are in runs `plan` again with it before extracting.

2. **Papers.** If they pointed you at their own papers, import them, search for nothing, and go on to step 3 -- see [Bring Your Own Papers](#bring-your-own-papers). Otherwise Paper Finder searches with the plan's search query, and the top papers are fetched into the project:

   ```bash
   theorize -p <run>/theory papers search "<the plan's search query>"
   theorize -p <run>/theory papers fetch --top <papers>
   theorize -p <run>/theory show papers
   ```

   Paper Finder's order is the ranking: fetch from it first. If fewer than the target come back with full text, search again from another angle on the question and fetch from that search, until the target is reached:

   ```bash
   theorize -p <run>/theory papers search "<another angle on the question>" --save-as search-2
   theorize -p <run>/theory papers fetch --top <papers still needed> --from search-2
   ```

   If the target is still not reached, go on with the papers that have full text. Theorizer extracts from full text only, so do not add abstract-only papers some other way. When you report the theories, say how many papers they rest on, out of the target.

   If the person gave papers, `papers import` adds them: see [Bring Your Own Papers](#bring-your-own-papers). When they say their papers are the corpus, import them and search for none.

3. **First pass.** Theorizer extracts from every paper with the plan's schema, and generates theories:

   ```bash
   theorize -p <run>/theory extract
   theorize -p <run>/theory theories generate --max-data-tokens 750000
   theorize -p <run>/theory show theories
   ```

   `--max-data-tokens` is how much evidence one generation call reads before it subsamples; 750000 fits `gpt-6-sol`. With 200 papers or more, add `--objective attribution-batched` to every generation in the run: it reads the evidence that does not fit in further batches instead of leaving it out. Say so in the plan.

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

6. **Updates.** After every generation, tell the person what the pass produced. If you have a tool for publishing artifacts, publish the theories with it too.

7. **Summary.** End the run by clustering the theories from every pass by the explanation they give. Theories from different schemas often restate each other; a cluster that several schemas reached rests on more of the evidence than one only a single schema produced. For each cluster, say what it is about in plain language and then in a few technical sentences, and why the person should care. Weigh the clusters by similarity, impact and novelty, and point the person to the ones they are likely to find most interesting, so they can find them quickly without reading every theory. Cluster even when the person asked for a theory shape: state each cluster's laws in that shape, in its technical sentences.

## Bring Your Own Papers

```bash
theorize -p <run>/theory papers import <their folder>      # every .md, .txt and .pdf under it
theorize -p <run>/theory papers import <files or a glob>
theorize -p <run>/theory show papers
```

Markdown is read as it is. PDFs are converted on import; add `--ocr mistral` for scanned PDFs when `MISTRAL_API_KEY` is set. Figures are not read: a markdown file that refers to them as image tags hands those tags over as text.

Import spends one small LLM call per paper on metadata, and a brought corpus has no paper target to bound it. Say the count when you show the plan, and say that step 4b extracts over every paper again for each schema it produces.
