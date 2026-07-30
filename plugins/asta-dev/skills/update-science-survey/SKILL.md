---
name: update-science-survey
description: Add, correct, or expand an entry in the AI-for-Science Survey (allenai/ai-for-science-survey). Use when a paper is missing from the survey, a citation is wrong, or a section needs a new development covered.
allowed-tools: Bash(git clone *) Bash(git checkout *) Bash(git add *) Bash(git commit *) Bash(git push *) Bash(gh pr create *) Bash(gh pr view *) Bash(make *) Bash(curl *) Read Write Edit
---

# Update the AI-for-Science Survey

The [AI-for-Science Survey](https://github.com/allenai/ai-for-science-survey) is a
living Quarto survey of AI agents for science and the publishing infrastructure
around them. It reads at <https://allenai.github.io/ai-for-science-survey/>. This
skill covers adding a missing paper (the common case), fixing a citation, or
expanding a section. Every change lands through a branch + PR — never push to `main`.

## Repo shape (what you edit)

- `references.bib` — every citation. **Not alphabetical**; entries are grouped by
  when they were added. Key convention: `<firstauthorlastname><year><shortname>`,
  e.g. `wu2026novbench`, `han2026drpg`. Brace any acronym/proper-noun capitals so
  BibTeX preserves them: `title={{FrontierScience}: Evaluating {AI}'s ...}`.
- `index.qmd` — the survey landing page (front matter + section map).
- `docs/ai-for-science.qmd` — the main narrative (Research Agents, Benchmarks,
  Publishing Platforms, Peer Review, …). Papers are cited inline as `[@key]`.
- `docs/general-ai-advances.qmd` — companion page for general-purpose AI advances
  that are *not* specific to AI-for-science. Put a paper here only if it isn't
  itself about AI-for-science.
- `_contributors.md`, `CITATION.cff`, `CITATION.bib` — **generated** from git
  history by `scripts/generate.py`; never hand-edit. `contributors.conf` controls
  who is listed.

## Workflow

### 1. Clone and branch

```bash
git clone https://github.com/allenai/ai-for-science-survey.git
cd ai-for-science-survey
git checkout -b add-<short-slug>
```

### 2. Find the paper and confirm it's genuinely missing

Use the Asta literature tools (`find-literature`, `semantic-scholar`) or the
Semantic Scholar API to identify the paper and pull authoritative metadata
(exact title, author order, year, venue, DOI/arXiv id, `CorpusId`). To surface
candidates the survey may have missed, sort by citation count within a year:

```bash
curl -s -H "x-api-key: $S2_API_KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=AI+for+science&year=2026&sort=citationCount:desc&fields=title,year,citationCount,externalIds,authors"
```

**Dedup carefully before adding — the survey is large (150+ entries).** A plain
title grep misses entries whose acronyms are brace-wrapped (`{AI}`) and misses
papers already cited under a different title (a preprint later published in a
journal). Cross-check by author surname, distinctive un-braced title tokens, and
the numeric `CorpusId`/arXiv id, and read the `note=` fields — an entry may
already cover the work you're about to add.

### 3. Add the citation and cite it in the narrative

Add a `@article{...}` (or `@inproceedings{...}`) entry to `references.bib`
following the key convention above, then add the paper where it belongs in the
narrative — match the surrounding prose style (the benchmark list uses
`- **Name** [@key]: one-line description`; body paragraphs weave `[@key]` inline).
Place it by topic, not at the end of a list, and keep the one-liner substantive
(what it is + why it matters), not just a title restatement.

### 4. Check, push, open the PR

```bash
make check   # generated-file sync + Quarto render/validate (needs quarto + full git history)
```

`make check` needs Quarto and the repo's pinned toolchain. If your environment
lacks it (e.g. a dispatcher turn with no Docker/Quarto), don't hand-wave the
gate — run it in the survey's CI toolchain image (`ghcr.io/allenai/asta:latest`,
which the repo's shared `workspace-quarto-site` workflow uses) or let GitHub CI
run it on the PR, and say which you did.

```bash
git add references.bib docs/ai-for-science.qmd
git commit -m "Add <paper> to the survey"
git push -u origin add-<short-slug>
gh pr create --repo allenai/ai-for-science-survey \
  --title "Add <paper> to the survey" \
  --body "What + why, with the citation metadata and the section it lands in."
```

Leave the merge to a human; the PR is the deliverable. After pushing, watch CI
and fix any render/citation failures.
