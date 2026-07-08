# Full-text extraction at scale

Some threads are FULL-TEXT-MANDATORY: the answer fields live in the paper BODY, not the abstract
(typical body-only fields: resources/inputs used, provenance/what-builds-on-what, verbatim
procedure passages, mechanism details). Other threads are abstract-sufficient (a per-paper claim
that abstracts state well). Decide the evidence tier per thread, with a pilot — don't assume.

## Decide the tier (pilot first)
Extract the schema from ~25 abstracts. If the answer fields are systematically ABSENT (only a
small fraction name the datasets / state the parent / give the mechanism), the thread is
fulltext-mandatory. If abstracts carry the fields, stay abstract (cheaper, full coverage). Record
the decision as `evidence_tier` in thread.json and say which tier each answer used.

## The full-text pipeline (cache-first map-reduce)
1. **Fetch once, cache** — `scripts/fulltext.py fetch(corpusId, arxiv, cache_dir)`: arxiv-html →
   ar5iv → None. Reachability ~90% for arXiv-era corpora; older/closed venues lower. REPORT the
   residual (unreachable + no-arxiv) — it's a real evidence-coverage ceiling, not a silent gap.
   The cache (`<run>/fulltext-cache/*.md`) is the "papers-with-bodies" collection: re-extraction
   under a new schema/lens costs ZERO fetches.
2. **Section-digest** — `fulltext.digest(text, want=...)` extracts the relevant sections
   (data/architecture/etc.) into a compact ~5–7K-char input, so extractors feed on targeted
   sections not 250K-char papers. CAVEAT: heading-matching is heuristic — VERIFY digests aren't
   empty/thin before extracting; systems/framework papers legitimately have no data section
   (extract null, don't hallucinate). Fall back to head-of-paper when nothing matches.
3. **Map** — batch reports across subagents; each reads its digest from cache (NEVER re-fetches)
   and extracts the thread.json extraction_schema, grounding each field in a verbatim span. Use
   per-batch isolated output files (shared scratch corrupts parallel runs).
   **INCREMENTAL-WRITE DISCIPLINE (every worker, every long job):** APPEND each record to the
   output JSONL as it is produced — never hold results for one final Write. On start, read the
   output file if it exists and SKIP already-done ids. Why: a stalled/killed worker that wrote
   nothing loses ALL its work (this happened — a 10-minute agent died at a watchdog with zero
   output); with append+skip, the orchestrator sees live progress (`wc -l`) and a relaunch of the
   SAME prompt RESUMES instead of redoing. Same principle as checkpointed fetches
   (acquire.fetch_edges): long work is resumable work.
4. **Reduce** — aggregate per sub-question with gates (below).

## Two-tier evidence pattern
Abstract skeleton across ALL papers (cheap, full coverage) + full-text deep where it matters (or
all, if fulltext-mandatory). Stamp `evidence_depth` (fulltext | abstract | none) per record so
every aggregate can report its evidence mix.

## Extraction gates (refuse to quote a shallow aggregate)
- extraction-coverage = fraction of the target with a record (separate the data-availability
  ceiling, e.g. no-abstract/unreachable, from true extraction misses — a data limit must not
  masquerade as an extraction failure).
- evidence-grounding = fraction with a verbatim span present.
- low-confidence fraction; evidence-depth mix.
Aggregation refuses (or flags) when the mix is too shallow to trust.

## Aggregation patterns (reduce)
- Frequency tables (which resources/methods appear across papers) — normalize free-text via a
  derived codebook first.
- Entity graphs (X extends/derives-from Y, what was kept vs changed) — directed edges from a
  per-record relation field.
- **Entity-dedup before counting** — when the question asks "used by ≥N *distinct* entities",
  collapse variants/siblings of the same underlying entity to one before the count (a practice
  found only within one entity-family fails the ≥N-distinct bar). Derive the "same family"
  relation from the corpus (e.g. the extends-graph), then count families, not instances.

## Infra note
This map-reduce fan-out is currently instruction-guided (batched subagents). It is the strongest
candidate to formalize as a single deterministic workflow (fan-out → gate → reduce) — until then,
keep batches isolated and read from cache.
