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
This skill is a **methodology + deterministic tools**. Throughout, steps are marked **[T]**
(Tool — deterministic, script-computed, exactly reproducible: merges, tallies, coverage
estimators, gate checks, chart data) or **[J]** (Judgment — a mind's call, yours or a
subagent's: relevance, tagging, extraction, synthesis, the coverage verdict). The rule:
**never fake a [T] with an LLM** (don't have a model eyeball a number a script should compute)
and **never fake precision on a [J]** (don't dress a judgment as if it were exact). The whole
trust story is this separation — a reader can re-run every [T] and audit every [J].

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
  in/relevant/maybe/not-relevant). Ask at Step 0 only what BLOCKS the first sweep; defer other
  scope-edge questions to the scope-charter beat — questions asked after first contact with the
  data are visibly better-informed (measured across runs).
- **scope.axis**: `folded` when relevance IS the scope test; `separate` when a paper can be
  relevant-shaped but off-scope on an orthogonal axis (fill `out_of_scope_families` only AFTER
  codebook derivation exposes them). When the user says "include both X and Y" (eras, kinds,
  populations), record them as `scope.strata`: include both, POOL NEITHER — deliverables are
  computed per-stratum (or primary-stratum-only with the rest reported separately). Pooling
  strata the user explicitly distinguished corrupts every count downstream.
- **extraction_schema**: design fields from the question's sub-questions (what does each paper
  analyze/use/find/extend...). Include per-record: evidence span, confidence, and a `scope_flag`
  escape (extraction reads deepest — it catches scope leaks nothing else sees).
- **evidence_tier**: decide per `references/fulltext-at-scale.md` — PILOT abstracts first; if the
  answer fields are systematically absent from abstracts, the thread is fulltext-mandatory.
- **thread.json is LIVING config**: when the executed schema evolves mid-run (fields renamed/
  added — it will), write the change BACK into thread.json (bump a version note) + MANIFEST.
  Config must describe what actually ran, or downstream consumers read a stale contract.

## Cost gate (HARD — get explicit approval BEFORE the first acquisition fan-out)
This pipeline is a significant commitment, not a search. After Step 0 (and at most one cheap
sizing probe — a single `find` call to gauge the space), STOP and present, in one short block:
- **Scale estimate**: expected corpus size for this thread (measured reference: 300–500-core
  threads ran ~2,000–2,500 candidates judged; scale the numbers if this thread looks smaller).
- **Time**: ~2–2.5 hours ACTIVE session time (measured), wall-clock longer with background waves;
  the user's own attention is needed at ~4–5 decision beats.
- **Tokens/cost order-of-magnitude**: measured full runs consumed ~0.3–0.5M model-output tokens
  plus 100–160M cache-read (≈ $230–330 at API list prices per run, ~$0.5–0.9 per core paper;
  subscription quotas differ). Cache-read is ~60% of the bill — cost ≈ context × call-count,
  not generation. Say "low-to-mid hundreds of dollars at list / a sizable slice of a daily
  quota", not a false-precise number.
- **Lighter alternatives**: a plain find-literature search (~minutes), or a snowball-only
  quick pass — offer them honestly; some questions don't need a corpus.
Proceed only on explicit approval ("go" / a chosen alternative). If mid-run scope grows
materially past the approved scale (e.g. a STOP/CONTINUE beat proposing a large tail round),
the costed options at that beat renew the consent — never silently 2× the approved commitment.

## The pipeline (each phase has a reference doc; read it when you get there)
1. **Acquire** — FIRST write a ~5-line **habitat note** into the run dir: where does this
   population live (academia / industry / practice / code), WHO ELSE ALREADY KEEPS A LIST of it
   ("find the librarians": registries, leaderboards, review tables, curated lists, trial
   registries), and **≥2 candidate modalities NOT in the list below — justify or refute each**.
   The modality list here is EXEMPLARS + a FLOOR, not the population: a checklist satisfies
   diligence ("did I run the list?") — the habitat note restores the real question ("have I
   found everything?"). A real run skipped it and missed the asker's #1 named item.
   Then run multi-modal — sweep at MODEST CONCURRENCY (~3-4 parallel finds: search backends
   run few searches concurrently and their request timeout counts queue wait, so a wide parallel
   burst just converts the tail into timeouts). Queries independent, but know that every
   paper-finder surface shares ONE relevance filter (calibrated consequence: corroboration and capture-recapture overstate
   independence — playbook §1): parametric seed enumeration →
   `asta literature` search/snowball + backward co-citation → survey-reference pooling →
   **web/registry enumeration when the population lives outside academia** (registries,
   leaderboards, aggregators, Wikipedia list-articles — enumerate, resolve entries to
   papers/reports, judge; see the playbook §1 doctrine) →
   gap-directed sweeps where earlier modalities proved weak → forward citations for recency.
   Tag every candidate with its modality (provenance). Mechanics live in `scripts/acquire.py`
   (resolve_titles — scored matching, never take the first hit; fetch_edges; pool_references;
   candidates_from_asta_find; merge_candidates). Cache everything via `scripts/s2.py`.
   **Retrieval division of labor** (each tool's comparative advantage — use accordingly):
   - `asta literature find` — one-shot ranked search; best for SWEEPS of independent query
     angles (per-query output files = per-query provenance). Pass `--include-rejected sample`
     when the server supports it: drop statistics + a stratified sample of dropped rows land in
     a `.rejected.json` SIDECAR (coverage-audit input — scripts read it; never pull it into your
     context; the sample costs the session nothing).
   - `asta literature interactive` — the full paper-finder agent: query DECOMPOSITION planning +
     a results-verification loop. Inside THIS skill your own loop already does decomposition and
     iteration, and the one measured run found interactive the highest-PRECISION surface but with
     ZERO unique-relevant yield (everything it found, find/snowball/citances also found). Treat
     it as an optional precision/validation probe or for one-off gnarly semantic questions — not
     as a corpus recall workhorse (evidence is n=1; re-measure if your thread differs).
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
   codebook from elsewhere. REQUIRED GATE after codebook@v1: the **parametric family anchor**
   (codebook.md §anchor) — corpus-derived codebooks are circular and cannot see a whole missing
   family; the blind-enumerated anchor is the validated check for that class.
4. **Substrate** — `scripts/substrate.py`: one observation record per paper, RINGS
   (core/candidate/maybe/unjudged/out), stage-coverage GATES. All downstream reads THIS.
   **After EVERY candidates-merge or substrate rebuild, run `scripts/validate.py <run>` and stop
   on failure.** Count checks can't catch content rot (a provenance-union regression keeps counts
   perfect while corroboration inputs corrupt) — only the machine-checked invariants can. If you
   deliberately defer judging part of a modality file, DECLARE it in thread.json `acq_deferred`
   (and say so in the coverage boundary) — deferral must never be silent.
5. **Coverage** — `scripts/coverage_signals.py` computes the [T] signals; YOU triangulate them
   into a verdict + confidence + ranked gaps (`references/coverage-playbook.md`), loop gaps back
   to Acquire until converged-or-bounded, and state the honest boundary. **REQUIRED signal — the
   known-canon anchor:** enumerate the area's canon parametrically, then check it against the
   store with `scripts/knowledge.py` `anchor()` (offline) — report recall + how absences were
   judged. A verdict without the canon check has a hole in it. `knowledge.py` (lookup / find /
   cites / anchor) is ALSO how you query the substrate for any preliminary view or answer —
   prefer it over ad-hoc jq (it knows the 3-layer membership semantics).
6. **Extract & answer** — per-paper extraction (map) over the evidence tier
   (`references/fulltext-at-scale.md` for fulltext threads), then aggregate (reduce) per
   sub-question with gates. Extraction schemas include a **mentioned-entities field** (the
   thread's pertinent entity types: models/methods/datasets the paper COMPARES AGAINST, not just
   its own subject) — nearly free at extraction time, and its inversion is a validated coverage
   signal (playbook §5: mention-shadow). TWO HARD OUTPUT REQUIREMENTS (not optional style):
   - EVERY answered sub-question carries its own "**How performed:**" note (corpus + ring +
     method + evidence tier + limits) — per-answer, in place; a single global methods header
     does NOT satisfy this.
   - EVERY paper reference in a user-facing artifact is a WORKING link — default
     `https://api.semanticscholar.org/CorpusId:<corpusId>`; if not on S2, link arXiv/DOI/
     publisher/the post itself. A bare corpusId is not clickable.
   For "disagreement" questions: support-gated field-spanning axes + a synthesis pass, never
   one-vs-two-paper spats (`references/answers.md`). The final user-facing deliverable is the
   REPORT — shape and content requirements in `references/report.md` (index page, per-question
   method notes, evidence in-body, data-generated distribution charts, self-contained rendering,
   the package). Do NOT source deliverable structure from generic artifact/design skills.

## Worker discipline (HARD — every long-running subagent job, all phases)
Judging waves, extraction batches, fetch sweeps, tagging runs: the worker APPENDS each result as
it is produced (never write-at-end) and SKIPS items already present in its output file
(idempotent resume). A stalled write-at-end worker loses everything; an append-as-produced worker
resumes for free, and `wc -l` is live progress. **Put these two instructions in every worker
prompt verbatim** — doctrine that lives only in a phase reference does not reach spawned workers.

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
  contested edges (they decide scope, you decide mechanics). Do NOT self-adjudicate contested
  edges silently, even when confident — surfacing them IS the beat (the one run that skipped it
  was right on the merits and still wrong on process: the user never saw the edge existed).
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
      s2-cache/  fulltext-cache/  extract/  MANIFEST.md  README.md  <answers>.md
```
**README.md = the run DASHBOARD (required; rewrite it at every beat/phase change, keep ≤25 lines):**
phase · state counts (candidates/judged/rings + gate statuses) · NEXT action · BLOCKED-ON ·
a MAP of where everything lives (deliverables vs state vs canonical inputs vs scratch vs caches) ·
the decisions so far (scope charter, tier, deferrals) as one-liners. Keep deliverables findable;
keep working/batch files in dedicated subfolders, not the run root — a flat 20+-entry root is
unnavigable for the next reader.
**WIRE IT INTO THE HARNESS (required — README.md alone has NO special status; nothing auto-reads
it):** at Step 0, write a stub **`CLAUDE.md`** (and **`AGENTS.md`** for Codex) at the session's
working directory:
```
Active corpus-research run: <run-dir>/
BEFORE acting: read <run-dir>/README.md (live dashboard: state · gates · NEXT · map).
Lineage/history: <run-dir>/MANIFEST.md. Config: <run-dir>/thread.json.
Re-read README.md after any compaction/resumption — it is the source of truth for run state.
```
Rationale: CLAUDE.md is what the harness ACTUALLY auto-loads (session start, persists across
compaction); skills only load when triggered, so a resumed session that never re-fires this skill
would otherwise land blind. The stub is written once; the dashboard stays the living file.

## Known limits (say so, don't hide)
Full-text reachability ~90% for arXiv-era corpora (report the residual). Section-digest matching
is heuristic — verify digests aren't empty before extracting. No corpus-local semantic search yet
(keyword + structure + citation only). S2 access MUST be serialized through `scripts/s2.py` —
parallel direct fetching gets rate-limited.
