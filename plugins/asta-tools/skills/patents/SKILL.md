---
name: patents
description: Look up, BM25-search, and trace citations for USPTO patents (grants and applications) via the S2 public API. Use to pull patent context into a session — find patents on a topic, fetch a patent's full detail by UCID, or list patents that cite a given paper.
allowed-tools: Bash(asta patents *)
---

# Patent Lookup

Fast, targeted lookups over the USPTO patent corpus (grants and applications)
using the `asta patents` commands. Patents are served by the same S2 public API
as papers, so the auth and configuration are shared with the `semantic-scholar`
skill.

## When to Use This Skill

- User asks about a specific patent (by UCID) or wants its claims / specification
- User wants a keyword search across patent title, abstract, claims, and specification
- User wants to know which patents cite a given paper (forward citations)
- A task needs patent context (prior art, assignee activity, paper-to-patent impact)

Ranking this sprint is **BM25 lexical only** — no semantic / vector search. Phrase
queries as keywords, not natural-language questions.

## Available Commands

### Search patents (BM25)

**asta patents search** — lexical search over title, abstract, claims, specification.

```bash
asta patents search "graphene battery electrode"

asta patents search "mRNA lipid nanoparticle" --limit 20

asta patents search "solid state battery" --fields ucid,title,assignees --format text
```

Options:
- `--fields`: Comma-separated fields (`ucid` always included). Default
  `ucid,title,publicationDate,assignees`.
- `--limit`: Max results (default 10, max 100)
- `--offset`: Starting position for pagination (default 0)
- `--format`: `json` (default) or `text`

Note: `claims` and `specification` are searchable but **not** returned in search
hits — fetch them per-patent with `asta patents get`.

### Get patent detail

**asta patents get** — full metadata for one patent by its UCID.

```bash
asta patents get US-10123456-B2

asta patents get US-10123456-B2 --fields ucid,title,claims,specification

asta patents get US-10123456-B2 --format text
```

UCID (Unified Citation Identifier) form: `<office>-<docNumber>-<kind>`, e.g.
`US-10123456-B2`. The detail endpoint can return the full `claims` and
`specification` text (omitted by default because they are large).

Available fields: `ucid, office, docNumber, kind, patentType, filingDate,
publicationDate, assignees, inventors, cpcCodes, title, abstract, claims,
specification, citedPaperCorpusIds`.

### Forward citations (paper → patents)

**asta patents forward-citations** — patents that cite a given paper.

```bash
asta patents forward-citations 215416146

asta patents forward-citations 215416146 --limit 20 --format text
```

The argument is the S2 `corpusId` of the paper (an integer). Pair this with the
`semantic-scholar` skill: resolve a paper to its corpusId with
`asta papers get <ID> --fields externalIds` (read `CorpusId` from the response),
or pass a `CorpusId:<n>` id directly — then feed the integer here to see
downstream patent impact.

## Response Shape

All commands return the standard S2 envelope:

```json
{ "total": 42, "offset": 0, "next": 10, "data": [ { "ucid": "US-...", "title": "..." } ] }
```

`get` returns a single patent object (no envelope).

## Notes & Limitations

- **Availability**: the patent cluster returns `503` until it has been fed. Until
  then these commands surface that error verbatim — that is expected, not a bug.
- **BM25 only**: no semantic/vector/hybrid ranking, no author linking this sprint.
- **Corpus**: USPTO grants (and applications, sharing the `patent` keyspace).
