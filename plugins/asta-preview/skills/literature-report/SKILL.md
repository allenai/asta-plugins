---
name: Asta Literature Reports
description: Create or update literature reviews/reports. Use whenever you need to research, summarize, or synthesize the literature.
allowed-tools:
  - Bash(asta literature find *)
  - Bash(asta literature report *)
  - Read(.asta/literature/*)
  - TaskOutput
---

# Literature Reports

Generate comprehensive literature reports by finding relevant papers and synthesizing them into a structured written report with citations.

## Finding Papers

- Check `.asta/literature/find/` for existing search results before running new searches.
- Use the **Find Literature** skill for comprehensive searches and for the result schema and jq access patterns.
- Use the **Semantic Scholar Lookup** skill for targeted queries: specific papers, citations, and author searches.

## Workflow Guidance

- **Identify or create the report file first**. Check if there's an existing report to update. New reports go in user-visible locations (e.g., `docs/`), not inside `.asta/`.
- **When updating an existing report**, read it first to understand the current structure and content.
- **When using Find Literature results**, go through ALL highly relevant papers — extract relevance criteria, snippets, and citation contexts from each.

**If the user provides an existing paper-finder results file:**
- Skip to step 3, using that file as `-i`

**If no existing results file:**
- Proceed to step 2

### 2. Find Papers

```bash
asta literature find 'query' --timeout 300 -o .asta/literature/find/YYYY-MM-DD-topic-slug.json
```

Note the output path from the command.

### 3. Generate the Report

```bash
asta literature report \
  -i .asta/literature/find/YYYY-MM-DD-topic-slug.json \
  -o .asta/literature/report/YYYY-MM-DD-topic-slug.md
```

The command prints progress to stderr and the report path when done.

### 4. Confirm and Share

- Read the saved report file and share the key findings with the user
- Tell the user the file path so they can open it

## Citation Conventions

**YAML frontmatter** — required for citation resolution:
```yaml
---
bibliography: ../references.bib
---
```

**Citations**: Use `[@key]` format. Every key must exist in the `.bib` file — unresolved keys won't render.

**Adding papers to `.bib`**: As you cite a paper, fetch its metadata and append a BibTeX entry:

```bash
asta papers get CorpusId:<id> --fields title,authors,year,venue,externalIds,journal,publicationDate
```

Generate a BibTeX entry from the result. Conventions:
- **Key**: `{firstAuthorSurname}{year}` lowercased, ASCII only (e.g., `wei2022`). Append a letter for conflicts (`wei2022a`).
- **`corpus_id`**: Include `corpus_id = {<id>}` for stable identification (survives key renames).
- **Append** to the `.bib` — never rewrite existing entries.

**Verification**: Use the **Preview** skill to render and verify all citations resolve.

## Error Handling

- **Authentication error**: Run `asta auth login` and retry
- **Timeout**: Pass a larger `--timeout` value (default is 360s)
- **No papers found**: Suggest refining the query and re-running `asta literature find`
