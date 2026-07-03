---
name: corpus-research
description: This skill should be used when the user asks for a "comprehensive list of papers on", "coverage of a research area", "corpus-scale analysis", "what does each paper in an area do/use/find", "cases of disagreement across the literature", "build a research corpus", or any literature question whose answer must aggregate/extract across MANY papers with trustworthy coverage — beyond a single search.
metadata:
  internal: true
allowed-tools: Bash(asta literature *) Bash(asta papers *) Bash(python *) Bash(jq *) TaskOutput
---

# Corpus research — comprehensive, trustworthy, grounded literature analysis

Build ONE rich corpus for a research thread, then work OVER it: coverage you can defend,
per-paper extraction grounded in sources, aggregate answers that carry their own trust story.
This skill is a **methodology + deterministic tools**; the judgment steps (relevance, tagging,
extraction, synthesis) are yours/subagents'. Never fake the [T] parts with an LLM; never fake
precision on the [J] parts.

## Principles (the north star — internalize before starting)
1. **Corpus-first.** Build the corpus, then every operation queries the OWN store first
   (`scripts/knowledge.py`); external fetch is the cache-miss fallback and every fetch folds back
   into the corpus (cache everything: metadata, edges, full text). Parametric knowledge PROPOSES
   (seed candidates, canon lists); the corpus ADJUDICATES. Corpus-first is only trustworthy with
   an honest boundary signal — always pair it with coverage estimation, or it's a filter bubble.
2. **Grounded, not parametric.** Every extracted fact carries a verbatim evidence span + source;
   every answer says which papers/ring produced it. The user should be able to touch raw sources.
3. **Provenance + gates everywhere.** Every artifact records what produced it (batch, method,
   coverage); every stage has a coverage/quality GATE that makes gaps POP (see
   `references/data-discipline.md`). Never let a quality drop hide in a catch-all bucket.
4. **Honest coverage.** Multi-modal acquisition + population estimates + an explicit boundary.
   Never claim "comprehensive" from one modality; never quote a flat "% missing" (stratify
   canonical vs long-tail). See `references/coverage-playbook.md`.
5. **Adopt, don't reinvent.** Retrieval = `asta literature find/interactive/snowball` (see the
   find-literature skill). Statistics = the exact published estimators in
   `scripts/coverage_signals.py`. Build only what's genuinely new for the thread.

## Step 0 — derive the THREAD CONFIG (you must do this; nothing is pre-filled)
From the user's question alone, write `<run>/thread.json`:
```json
{"name": "<slug>", "question": "<verbatim>",
 "criteria": [{"id": "crit_1", "name": "...", "definition": "what makes a paper relevant, per criterion"}],
 "scope": {"axis": "folded|separate", "out_of_scope_families": []},
 "extraction_schema": {"<field>": "<what to extract, per the question's sub-questions>"},
 "evidence_tier": "abstract|fulltext"}
```
- **criteria**: decompose the question into per-criterion relevance tests (graded 0–3, tier =
  in/relevant/maybe/not-relevant). Confirm scope edges with the user when ambiguous.
- **scope.axis**: `folded` when relevance IS the scope test; `separate` when a paper can be
  relevant-shaped but off-scope on an orthogonal axis (fill `out_of_scope_families` only AFTER
  codebook derivation exposes them).
- **extraction_schema**: design fields from the question's sub-questions (what does each paper
  analyze/use/find/extend...). Include per-record: evidence span, confidence, and a `scope_flag`
  escape (extraction reads deepest — it catches scope leaks nothing else sees).
- **evidence_tier**: decide per `references/fulltext-at-scale.md` — PILOT abstracts first; if the
  answer fields are systematically absent from abstracts, the thread is fulltext-mandatory.

## The pipeline (each phase has a reference doc; read it when you get there)
1. **Acquire** — multi-modal, each modality blind to the others: parametric seed enumeration →
   `asta literature` search/snowball + backward co-citation → survey-reference pooling →
   gap-directed sweeps where earlier modalities proved weak → forward citations for recency.
   Tag every candidate with its modality (provenance). Mechanics live in `scripts/acquire.py`
   (resolve_titles — scored matching, never take the first hit; fetch_edges; pool_references;
   candidates_from_asta_find; merge_candidates). Cache everything via `scripts/s2.py`.
   **Retrieval division of labor** (each tool's comparative advantage — use accordingly):
   - `asta literature find` — one-shot ranked search; best for SWEEPS of independent query
     angles (per-query output files = per-query provenance).
   - `asta literature interactive` — the full paper-finder agent: query DECOMPOSITION planning +
     a results-verification loop. Use it for the gnarly semantic queries ("X even if not using
     those words") where your hand-rolled angles may under-search, and when you want the agent
     to iterate until criteria are satisfied.
   - `asta literature snowball` — RANKED citation expansion (reranked against seed relevance),
     and **citances mode**: citation-CONTEXT snippets — a distinct discovery modality that finds
     papers by HOW they're cited and hands you judge-ready evidence. Raw S2 edges (s2.py) are
     for the GRAPH (complete, unranked — coverage signals); the snowball endpoint is for
     prioritized expansion + citances. Use both, for their different jobs.
2. **Curate** — relevance-judge every candidate against thread.json criteria
   (`references/curation.md`: cost-tiered judging, corroboration pre-filter, panel+adjudicator
   only for the borderline; strip search noise). Write judgment files → `scripts/relevance.py`.
3. **Codebook** (when the question needs content families) — DERIVE it from this corpus by
   grounded coding (`references/codebook.md`); apply as ordered tag batches. Never import a
   codebook from elsewhere.
4. **Substrate** — `scripts/substrate.py`: one observation record per paper, RINGS
   (core/candidate/maybe/unjudged/out), stage-coverage GATES. All downstream reads THIS.
   **After EVERY candidates-merge or substrate rebuild, run `scripts/validate.py <run>` and stop
   on failure.** Count checks can't catch content rot (a provenance-union regression keeps counts
   perfect while corroboration inputs corrupt) — only the machine-checked invariants can. If you
   deliberately defer judging part of a modality file, DECLARE it in thread.json `acq_deferred`
   (and say so in the coverage boundary) — deferral must never be silent.
5. **Coverage** — `scripts/coverage_signals.py` computes the [T] signals; YOU triangulate them
   into a verdict + confidence + ranked gaps (`references/coverage-playbook.md`), loop gaps back
   to Acquire until converged-or-bounded, and state the honest boundary.
6. **Extract & answer** — per-paper extraction (map) over the evidence tier
   (`references/fulltext-at-scale.md` for fulltext threads), then aggregate (reduce) per
   sub-question with gates. TWO HARD OUTPUT REQUIREMENTS (not optional style):
   - EVERY answered sub-question carries its own "**How performed:**" note (corpus + ring +
     method + evidence tier + limits) — per-answer, in place; a single global methods header
     does NOT satisfy this.
   - EVERY paper reference in a user-facing artifact is a WORKING link — default
     `https://api.semanticscholar.org/CorpusId:<corpusId>`; if not on S2, link arXiv/DOI/
     publisher/the post itself. A bare corpusId is not clickable.
   For "disagreement" questions: support-gated field-spanning axes + a synthesis pass, never
   one-vs-two-paper spats (`references/answers.md`).

## Interaction rhythm — you are collaborating, not executing a ticket  <!-- v1, tune with users -->
The user's most valuable input comes AFTER contact with the data — they can't react to a
distribution they haven't seen. Clarifying questions at Step 0 are NOT enough. Work in BEATS,
where each beat collects a DECISION or a steer (never a mere status update):
- **First steerable artifact within ~30 minutes:** after Step 0 + the first acquisition sweep,
  STOP and present: the shape of the space so far (candidate count, apparent clusters/eras), your
  proposed **scope charter** (boundary families in/out + the contested edges — different honest
  runs draw materially different boundaries; pin the edges WITH the user), and the plan. Long
  fetches keep running in the background while you talk.
- **Post-curation beat:** surprising exclusions + borderline patterns → the user rules on
  contested edges (they decide scope, you decide mechanics).
- **Coverage beat:** verdict + boundary → **STOP vs CONTINUE is the user's call** (it depends on
  their goal, which you don't fully know).
- **Early-answers beat:** preview headline distributions/findings from the partial corpus BEFORE
  deep extraction — lets the user start learning immediately and steer emphasis ("more X, skip Y").
- **Background the long work** (fetch sweeps, judging waves, extraction batches) and return to
  the user while it runs; fold results in at the next beat.
- For explicitly batch-shaped asks ("just deliver the full thing"), compress the beats — but the
  scope-charter beat and the coverage-verdict beat are never skipped.

## Run-dir layout (the working artifacts; keep a MANIFEST.md — see data-discipline)
```
<run>/thread.json  candidates.jsonl  judgments/  tag-batches/  scope-exclusions.json
      standardized-relevance.jsonl  observations.jsonl  edges-cache.json
      s2-cache/  fulltext-cache/  extract/  MANIFEST.md  <answers>.md
```

## Known limits (say so, don't hide)
Full-text reachability ~90% for arXiv-era corpora (report the residual). Section-digest matching
is heuristic — verify digests aren't empty before extracting. No corpus-local semantic search yet
(keyword + structure + citation only). S2 access MUST be serialized through `scripts/s2.py` —
parallel direct fetching gets rate-limited.
