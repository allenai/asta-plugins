---
name: Asta Literature Reports
description: Create or update literature reviews/reports. Use whenever you need to research, summarize, or synthesize the literature.
allowed-tools:
  - Bash(asta literature find *)
  - Bash(asta literature report *)
  - Bash(asta papers get *)
  - Bash(jq *)
  - Bash(mkdir *)
  - Read(.asta/literature/*)
  - Read(*)
  - TaskOutput
---

<objective>
Generate comprehensive literature reports by finding relevant papers and synthesizing them into structured written reports with citations. Route to the correct workflow based on what the user already has.
</objective>

<principles>
- **Check before searching.** Always check `.asta/literature/find/` for existing search results before running new searches.
- **Reports are user-facing.** New reports go in user-visible locations (e.g., `docs/`, project root), never inside `.asta/`.
- **Read before updating.** When updating an existing report, read it first to understand structure and content.
- **Exhaust the evidence.** When using find-literature results, go through ALL highly relevant papers — extract relevance criteria, snippets, and citation contexts from each.
- **Delegate search to the right tool.** Use the **Find Literature** skill for comprehensive searches. Use the **Semantic Scholar Lookup** skill for targeted queries (specific papers, citations, author searches).
</principles>

<routing>
Determine which workflow to follow based on what the user has:

**Route A — No papers yet** → The user wants a literature report but hasn't searched yet.
Read `workflows/find-and-report.md`.

**Route B — Has a find-literature result** → The user provides or references an existing `.json` results file from `asta literature find`.
Read `workflows/generate-report.md`.

**Route C — Has papers in another form** → The user has a collection of papers as a list of titles, DOIs, arXiv IDs, URLs, a BibTeX file, or any non-find-literature format.
Read `workflows/convert-and-report.md`.

**Route D — Merge into existing report** → The user has an existing report and wants to incorporate new papers or findings into it.
Read `workflows/merge-report.md`.

When the user's intent maps to multiple routes (e.g., "find papers on X and add them to my existing report"), chain the relevant workflows in sequence.
</routing>

<file_conventions>
**Search results:** `.asta/literature/find/YYYY-MM-DD-topic-slug.json`
**Generated reports:** `.asta/literature/report/YYYY-MM-DD-topic-slug.md`
**User-facing reports:** User-specified path or `docs/` directory
</file_conventions>

<citations>
Read `references/citation-conventions.md` when the report requires formal citations with a `.bib` file and `[@key]` references.
</citations>

<errors>
- **Authentication error** → Run `asta auth login` and retry.
- **Timeout** → Pass a larger `--timeout` value (default is 360s).
- **No papers found** → Suggest refining the query and re-running `asta literature find`.
</errors>
