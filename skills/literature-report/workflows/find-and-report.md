# Find Papers and Generate Report

Use when the user wants a literature report but has no papers yet.

<process>

## Step 1: Clarify the query

Ask the user to describe their research topic if the request is vague. The search query can be long and complex — a well-scoped query produces better results.

## Step 2: Check for existing searches

```bash
asta documents --root .asta/literature/find search --summary '<detailed query>' 2>/dev/null
```
If relevant results already exist, confirm with the user whether to reuse them or run a fresh search.

## Step 3: Run the search

Generate a slug from the topic (e.g., `transformer-efficiency`).

```bash
asta literature find '<detailed query>' --timeout 300 -o .asta/literature/find/YYYY-MM-DD-topic-slug.json
```

Run this in the background — it takes 30–60 seconds. When done, add it to the Asta document index
```bash
asta documents --root .asta/literature/find \
  add .asta/literature/find/YYYY-MM-DD-topic-slug.json
  --name="Literature Report: <concise query>" \
  --summary="<detailed query>" \
  --tags="find-literature,..." \
  --mime-type="application/json"
```

## Step 4: Review results

After the search completes, inspect the top results:

```bash
jq '[.results | sort_by(-.relevanceScore) | .[0:10][] | {title, year, venue, corpusId, score: .relevanceScore, summary: .relevanceJudgement.relevanceSummary}]' .asta/literature/find/YYYY-MM-DD-topic-slug.json
```

Share a brief summary of what was found (paper count, top themes) with the user before generating the report. If the results look thin or off-topic, suggest refining the query.

## Step 5: Generate the report

Now follow `workflows/generate-report.md` using the results file from step 3.

</process>
