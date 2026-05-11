# Generate Report from Find-Literature Results

Use when the user already has a `.json` results file from `asta literature find`.

<process>

## Step 1: Identify the input file

The user provides or references a results file. If it was created by an Asta skill, 
it will be in .asta/literature/find. Confirm the file exists.

## Step 2: Generate the report

```bash
asta literature report \
  -i .asta/literature/find/YYYY-MM-DD-topic-slug.json \
  -o .asta/literature/report/YYYY-MM-DD-topic-slug.md
```

Options:
- `--query "custom framing"` — override the query used as the report title/framing
- `--max-papers 30` — include more papers (default: 20, highest-relevance first)

The command prints progress to stderr and the report path when done.

## Step 3: Review and deliver

Read the saved report file. Share the key findings with the user, including:
- The main themes and conclusions
- Number of papers synthesized
- The file path so they can open it

If the user wants the report in a specific location (e.g., `docs/literature-review.md`), copy or move it there.

## Step 4: Citations (if needed)

If the report needs formal citations with a `.bib` file, follow `references/citation-conventions.md`.

</process>
