---
name: patents
description: Look up, BM25-search, and trace citations for USPTO patents (grants and applications) via the S2 public API. Use to pull patent context into a session, e.g. find patents on a topic, fetch a patent's full detail by UCID, or list patents that cite a given paper.
allowed-tools: Bash(asta patents *)
---

# Patent Lookup

targeted lookups over uspto grants and applications via `asta patents`.
patents share the s2 public api with papers.
auth and config are the same as the `semantic-scholar` skill.

## When to Use This Skill

- a specific patent by ucid, or its claims or brief summary
- keyword search across title, abstract, brief summary, claims, and party names
- which patents cite a given paper (forward citations)
- patent context for a task: prior art, assignee activity, paper-to-patent impact

ranking is **bm25 only**.
there is no semantic or vector search.
phrase queries as keywords, not questions.

## Available Commands

### Search patents (BM25)

**asta patents search** matches title, abstract, brief summary, claims, and party names.

```bash
asta patents search "graphene battery electrode"

asta patents search "mRNA lipid nanoparticle" --limit 20

asta patents search "solid state battery" --fields ucid,title,assignees --format text
```

Options:
- `--fields`: comma-separated fields. `ucid` is always included. default `ucid,title,publicationDate,assignees`.
- `--limit`: max results. default 10, max 100.
- `--offset`: pagination start. default 0.
- `--format`: `json` (default) or `text`.

`claims` and `briefSummary` are searchable but **not** returned in hits.
requesting them from search is a 400.
fetch them per patent with `asta patents get`.

### Get patent detail

**asta patents get** returns full metadata for one patent by ucid.

```bash
asta patents get US10123456B2

asta patents get US10123456B2 --fields ucid,title,claims,briefSummary

asta patents get US10123456B2 --format text
```

a ucid is `<office><docNumber><kind>` with **no separators**, e.g. `US10123456B2`.
the dashed display form `US-10123456-B2` is a 404.
copy the `ucid` from a search hit instead of assembling one.
`claims` and `briefSummary` are omitted by default because they are large.

available fields: `ucid, office, docNumber, kind, stage, docType, corpusId, filingDate, publicationDate, assignees, inventors, cpcCodes, title, abstract, claims, briefSummary, citedPaperCorpusIds`.
unrecognized fields are a 400.

### Forward citations (paper → patents)

**asta patents forward-citations** lists patents that cite a paper.

```bash
asta patents forward-citations 215416146

asta patents forward-citations 215416146 --limit 20 --format text
```

the argument is the paper's integer s2 `corpusId`.
resolve it with the `semantic-scholar` skill: `asta papers get <ID> --fields externalIds`, then read `CorpusId`.
`asta papers get` also accepts `CorpusId:<n>` directly.

## Response Shape

search and forward-citations return the standard s2 envelope:

```json
{ "total": 42, "offset": 0, "next": 10, "data": [ { "ucid": "US10123456B2", "title": "..." } ] }
```

`get` returns a single patent object with no envelope.

## Notes & Limitations

- **503**: the patent cluster is down or unfed. commands surface it verbatim.
- **bm25 only**: no semantic, vector, or hybrid ranking, and no author linking.
- **corpus**: uspto grants and applications, sharing the `patent` keyspace.
