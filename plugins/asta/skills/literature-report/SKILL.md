---
name: Asta Literature Reports
description: Create or update literature reviews/reports. Use whenever you need to research, summarize, or synthesize the literature.
allowed-tools:
  - Read(.asta/literature/*)
  - TaskOutput
  - Bash(jq *)
---

# Literature Reports

Create or update literature reviews/reports as markdown documents with citations.

## Finding Papers

- Check `.asta/literature/find/` for existing search results before running new searches.
- Use the **Find Literature** skill for comprehensive searches and for the result schema and jq access patterns.
- Use the **Semantic Scholar Lookup** skill for targeted queries: specific papers, citations, and author searches.

## Workflow Guidance

- **Identify or create the report file first**. Check if there's an existing report to update. New reports go in user-visible locations (e.g., `docs/`), not inside `.asta/`.
- **When updating an existing report**, read it first to understand the current structure and content.
- **When using Find Literature results**, go through ALL highly relevant papers — extract relevance criteria, snippets, and citation contexts from each.

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
