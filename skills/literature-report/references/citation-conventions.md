# Citation Conventions

Follow these conventions when a report requires formal citations with a `.bib` file and `[@key]` Pandoc-style references.

## YAML Frontmatter

Every report with citations must include:

```yaml
---
bibliography: ../references.bib
---
```

Adjust the relative path to point to the `.bib` file from the report's location.

## Citation Format

Use `[@key]` inline. Every key must exist in the `.bib` file — unresolved keys won't render.

## Adding Papers to the `.bib` File

As you cite a paper, fetch its metadata and append a BibTeX entry:

```bash
asta papers get CorpusId:<id> --fields title,authors,year,venue,externalIds,journal,publicationDate
```

Generate a BibTeX entry from the result. Conventions:

- **Key format**: `{firstAuthorSurname}{year}` lowercased, ASCII only (e.g., `wei2022`). Append a letter for conflicts (`wei2022a`, `wei2022b`).
- **`corpus_id` field**: Always include `corpus_id = {<id>}` for stable identification (survives key renames).
- **Append only**: Add new entries to the end of the `.bib` file. Never rewrite or remove existing entries.

## Verification

Use the **Preview** skill to render the report and verify all citations resolve. Unresolved `[@key]` references appear as literal text in the output — scan for any that didn't render as proper citations.
