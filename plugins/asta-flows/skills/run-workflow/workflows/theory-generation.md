# Theory generation

Build theories from the literature on a question. Paper Finder gathers the papers. Theorizer extracts findings from them and generates theories, then asks the papers which variables the first extraction missed and runs one more pass for each new schema. Every pass adds its theories to the same theory store.

## Plan

First ask the person in one short message, then wait for the answer:

- **Angle.** Should the theories focus on one part of the question, a mechanism, a subgroup or a kind of explanation?
- **Their papers.** Do they have papers that must be in the corpus, or that should be the whole corpus?

Offer what you would pick if they have no preference, in one line each. Do not search or fetch before they answer.

Then show them this table, with the values for their question. Everything not in it runs on the command's own default.

| Step | Agent | What it does | Configuration |
|---|---|---|---|
| 1 | Theorizer | Plans a paper search query, an extraction query and a first extraction schema from the question | `gpt-6-sol` |
| 2 | Paper Finder | Searches with the plan's query, fetches the top papers' full text, and fills any gap to the target with more searches | 100 papers (`papers fetch --top`) |
| 3 | Theorizer | Extracts findings from every paper and generates theories | extraction `gpt-6-luna`, generation `gpt-6-sol` |
| | Check-in | Shows you the first theories, then you steer another generation or go on | |
| 4 | Theorizer | Asks each paper what the first extraction missed, and designs new extraction schemas from the answers | usually 2 to 4 schemas |
| 5 | Theorizer | For each new schema: extracts findings, then generates theories | one pass per schema |

## Steps

`<run>/theory` is the Theorizer project. Every step saves into it, so the passes share one corpus and one theory store.

1. **Plan.** Theorizer plans the run from the question: a paper search query, an extraction query and a first schema:

   ```bash
   theorize -p <run>/theory init --model gpt-6-sol --extraction-model gpt-6-luna
   theorize -p <run>/theory plan "<the question>"
   ```

   If the person gave an angle, pass it as `--mission-statement`, so it shapes the search query and the schema. A workflow that adds a mission statement after the papers are in runs `plan` again with it before extracting.

2. **Papers.** Paper Finder searches with the plan's search query, and the top papers are fetched into the project:

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

   `--max-data-tokens` is how much evidence one generation call reads before it subsamples; 750000 fits `gpt-6-sol`. For a corpus of hundreds of papers, `--objective attribution-batched` reads the rest in further batches, at more cost.

   **Check in and wait.** Stop here even in an autonomous run: variable discovery and the schema passes cost several times the first pass. List the first theories, one line each, and offer two ways on:

   - **Steer the theories.** Generate again from the same findings, with the person's direction (a focus, a mechanism, a kind of explanation, theories to set aside) in the mission statement. Nothing is extracted again.

     ```bash
     theorize -p <run>/theory theories generate --max-data-tokens 750000 --mission-statement "<the question, then their direction>" --save-as theories-steer-<n>
     ```

     Report and publish it as in step 6, then check in again.
   - **Go on** to steps 4 and 5.

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

7. **Comparison.** Theories from different schemas often restate each other. Name the ones that do, and the ones only one schema produced. That tells the person which explanations rest on one slice of the evidence.

## Bring Your Own Papers

```bash
theorize -p <run>/theory papers import <their folder>      # every .md, .txt and .pdf under it
theorize -p <run>/theory papers import <files or a glob>
theorize -p <run>/theory show papers
```

Markdown is read as it is. PDFs are converted on import; add `--ocr mistral` for scanned PDFs when `MISTRAL_API_KEY` is set.
