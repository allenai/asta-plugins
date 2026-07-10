---
name: corpus-research
description: This skill should be used when the user asks for a "comprehensive list of papers on", "coverage of a research area", "corpus-scale analysis", "what does each paper in an area do/use/find", "cases of disagreement across the literature", "build a research corpus", "papers that discuss/address <topic>", a survey of "failure modes of X" / "approaches to X", a multi-question research need over one literature, "map the landscape/ecosystem of <tools/frameworks/models/products>", "what's out there for X and how do they compare" — the corpus members need not be papers (registries, repos, reports, and docs are corpora too) — or any question whose answer must aggregate/extract across MANY sources with trustworthy coverage, beyond a single search. Also invoke when a plain literature search is done and the user escalates ("this is for a longer-running project", "I need comprehensive/trustworthy coverage", "build a corpus") — a real user's first message often reads like a search request; the escalation moment is a trigger too.
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
5. **User touches the sources.** Hand verbatim excerpts + working pointers into papers, not
   only synthesis — provenance is necessary but not sufficient.
6. **Flex modes; surface the goal.** Interrogation is one mode, not a lock-in; after a few turns
   make the user's higher-level goal explicit, and steer stretched micro-operations to a more
   reliable route to the same goal.
7. **Adopt, don't reinvent.** Retrieval = `asta literature find/interactive/snowball` (see the
   find-literature skill). Statistics = the exact published estimators in
   `scripts/coverage_signals.py`. Build only what's genuinely new for the thread.

## Step 0 — derive the THREAD CONFIG (you must do this; nothing is pre-filled)
From the user's question alone, write `<run>/thread.json`:
```json
{"name": "<slug>", "question": "<verbatim>",
 "criteria": [{"id": "crit_1", "name": "...", "definition": "what makes a paper relevant, per criterion"}],
 "scope": {"axis": "folded|separate", "out_of_scope_families": []},
 "extraction_schema": {"<field>": "<what to extract, per the question's sub-questions>"},
 "evidence_depth": "abstract|fulltext"}
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
- **evidence_depth** (thread-level): decide per `references/fulltext-at-scale.md` — PILOT abstracts first; if the
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

## The pipeline (each phase has a reference doc; RE-READ it when you get there)
Re-read the phase's reference AT the phase even if you read it at session start — long runs span
compactions, and measured: structurally-enforced requirements survive them but prose-only
guidance decays (a run built its report 20h after its only read of the report reference and dropped exactly
the prose-specified requirements; a sibling run re-read at the phase and dropped none).
1. **Acquire** — FIRST write a ~5-line **habitat note** into the run dir: where does this
   population live (academia / industry / practice / code), WHO ELSE ALREADY KEEPS A LIST of it
   ("find the librarians": registries, leaderboards, review tables, curated lists, trial
   registries — and CHECK for an existing `librarian:*` roster from prior work on this thread,
   curation.md §librarian), and **≥2 candidate modalities NOT in the list below — justify or refute each**.
   The modality list here is EXEMPLARS + a FLOOR, not the population: a checklist satisfies
   diligence ("did I run the list?") — the habitat note restores the real question ("have I
   found everything?"). A real run skipped it and missed the asker's #1 named item.
   **Query floors + anchor diversity (both measured failure modes):** sweep angles must cover
   the CHARTER's ability/method families before any codebook exists — a corpus-derived codebook
   cannot see a family that was never queried (a run's sweeps skipped two charter families; the
   ~20 highest-cited misses clustered exactly there). And the parametric seed enumeration must
   run PER FAMILY-AXIS — derive the axes from YOUR thread (abilities × methods × eras ×
   adjacent subfields are the a2-shaped exemplars, not the list), never as one flat
   enumeration — a flat list inherits the same culture as your queries and anchors nothing (the same
   run's 54-seed anchor shared its sweeps' blind spot and caught zero of the misses).
   Then run multi-modal (diligent/escalated finds at ~3-4 parallel — backend timeouts count
   queue wait; all paper-finder surfaces share ONE relevance filter, playbook §1): parametric
   seed enumeration →
   `asta literature` search/snowball + backward co-citation → survey-reference pooling →
   **web/registry enumeration when the population lives outside academia** (registries,
   leaderboards, aggregators, Wikipedia list-articles — enumerate, resolve entries to
   papers/reports, judge; see the playbook §1 doctrine) →
   gap-directed sweeps where earlier modalities proved weak → forward citations for recency.
   Tag every candidate with its modality (provenance). Mechanics live in `scripts/acquire.py`
   (resolve_titles — scored matching, never take the first hit; fetch_edges; pool_references;
   candidates_from_asta; merge_candidates). Cache everything via `scripts/s2.py`.
   **Staged sweep policy (measured: fast is a truncated diligent, and blind fast cost a run
   most of its head recall):** (1) sweep ALL angles in `--mode fast`, each with
   `--include-rejected sample` (drop stats land in a `.rejected.json` SIDECAR — scripts read it,
   never your context); (2) ALWAYS also run the thread's PRIMARY question in `--mode diligent` —
   it calibrates what depth buys on THIS thread; (3) [T] escalation gate: rank fast queries by
   their own sidecar `not_judged` count (+ total_hits, + judged yield) and escalate a budgeted
   top slice (~25-30%) plus anchor-flagged thin families to diligent; stop when marginal
   new-yield flattens; (4) the verdict MUST name the binding cuts and the un-escalated remainder
   (a run that never read its own sidecars shipped an 85-90% head claim that measured ~44%).
   **Read playbook §1's retrieval division-of-labor BEFORE the first find call** (find vs
   interactive vs snowball/citances vs raw edges — each tool's measured comparative advantage).
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
   to Acquire until converged-or-bounded, and state the honest boundary. **REQUIRED signal: the
   known-canon anchor** via `knowledge.anchor()` (playbook §4) — a verdict without it has a hole
   in it. Substrate queries are ad-hoc joins over the standard files (measured: that's what
   works); `knowledge.anchor/lookup` cover the membership-semantics cases.
6. **Extract & answer** — FIRST materialize the collection view (`python scripts/knowledge.py
   view <run>` → collection.jsonl): the canonical id-normalized join every answer queries —
   ad-hoc joins run over the VIEW, never over the raw stage files (measured: 40+ hand-rolled
   re-joins per run, each re-deciding normalization). Rebuild it after any stage change.
   Then per-paper extraction (map) over the evidence depth
   (`references/fulltext-at-scale.md` for fulltext threads), then aggregate (reduce) per
   sub-question with gates. Extraction schemas include a **mentioned-entities field** (the
   thread's pertinent entity types: models/methods/datasets the paper COMPARES AGAINST, not just
   its own subject) — nearly free at extraction time, and its inversion is a validated coverage
   signal (playbook §5: mention-shadow). TWO HARD OUTPUT REQUIREMENTS (not optional style):
   per-answer "How performed" notes and working paper links on every reference — full spec in
   `references/deliverables.md` Part A, re-read at this phase. For "disagreement" questions: support-gated field-spanning axes + a synthesis pass, never
   one-vs-two-paper spats (`references/deliverables.md`). The final user-facing deliverable is the
   REPORT — shape and content requirements in `references/deliverables.md` Part B (index page,
   evidence in-body, distribution charts, self-contained rendering, the package). Do NOT source deliverable structure from generic artifact/design skills.
   **REPORT GATE [T] (HARD):** after building the report, run `python scripts/report_gate.py
   <report_dir> --run <run> --questions <n>` and fix-and-rerun until PASS — number tracing,
   boundary framing, method notes, links, self-containment. Produce-X-gate-X applied to the
   report; prose requirements decay, the gate does not.

## Worker discipline (HARD — every long-running subagent job, all phases)
Full contract: `references/workers.md` (re-read before ANY fleet fan-out). Build judge shards
with `scripts/shards.py` — stratified-interleave + salted gold items + k-chunked sub-batches:
measured lesson, prompts do not change worker behavior; STRUCTURE does (append-as-produced +
skip-already-done still go in every worker prompt verbatim, but the sub-batch shard format is
what actually enforces them). Score every judge wave with `shards.py score` (salt agreement =
drift alarms with evidence). Probe-canary one worker per operation before fanning out.

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
