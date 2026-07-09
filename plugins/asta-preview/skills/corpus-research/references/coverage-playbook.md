# Coverage playbook — honest, quantified comprehensiveness

Goal: a coverage VERDICT you can defend — `{captured, missing-estimate range, confidence, ranked
gaps, explicit boundary}` — never a bare "comprehensive" and never a single scalar.

## 1. Multi-modal acquisition (the only honest way in)
**Match the modality set to WHERE THE POPULATION LIVES — not to your tooling.** Academic indexes
(search, citation graph, survey references) enumerate *academic* literature; if the thread's
population is industry-adjacent or practice-driven (models, tools, systems, datasets, clinical
topics), the web has MAINTAINED ENUMERATIONS that academic modalities structurally miss:
registries, leaderboards, comparison/pricing aggregators, curated "awesome" lists, Wikipedia
list-articles, vendor documentation. These are BOTH an acquisition modality (enumerate → resolve
each entry to its paper/report → judge; some entries legitimately have no paper — record that)
AND a recall anchor. This doctrine has TWO halves — **CAPTURE** (accept off-index works as
first-class records) and **ENUMERATION** (actually sweep the maintained lists) — and a real run
used capture while skipping enumeration and missed the asker's #1 named item. The habitat note
(SKILL step 1) forces the enumeration question every time: who else already keeps a list of these?
**The INDEX does not define the population — but identity must stay robust (S2 = prime citizen):**
- **Primary key = the S2 corpusId whenever one exists.** Before minting anything synthetic,
  try S2 by EXTERNAL ID — `paper/arXiv:<id>`, `paper/DOI:<doi>` — title-search failing is NOT
  evidence of absence (a real round minted 2 unnecessary synthetics that direct lookup resolved).
- **Only then mint a synthetic key** (`web:<slug>`; `arxiv:<id>` only if the direct lookup truly
  404s), fetch the page/PDF into the fulltext cache under that key, and record ALL known
  identifiers in an `ids{}` field (arxiv/doi/url) so later resolution is possible.
- **Promotion with aliasing:** when an S2 id is later found for a synthetic-keyed record (arXiv
  papers DO get indexed), re-key the record and append `old→new` to the run's `id-aliases.json`;
  apply the alias map whenever merging any output still keyed by old ids. Joins must never break.
- Dedup resolution order across id spaces: `s2 > doi > arxiv > url-slug`.
- Synthetic-keyed items flow through rings/gates/extraction unchanged (ids are opaque strings);
  citation-graph signals won't cover them — say so in the coverage boundary.
Priority rule: a PROPER technical report must never be missed because of indexing; page-only
long-tail items are captured best-effort.

**The shared-filter caveat (calibrated, explains measured verdict overconfidence):** queries are
independent, but every paper-finder surface (find/interactive/snowball/citances) shares ONE
relevance reranker. Cross-modality corroboration partly measures filter agreement; CR occasions
correlate → N̂ biased DOWN. Treat modalities by FILTER LINEAGE: paper-finder-filtered vs
filter-independent (parametric enumeration, survey-ref pooling, raw-edge co-citation, raw-S2
sweeps, web lists). The retrieval filter's false-negative rate is a named verdict term —
UNMEASURED until the rejected-stats sidecar is available, then measured per thread by judging
the reject sample.

Run modalities with independent QUERIES, each blind to the others, tagging every candidate with
its modality (this list is EXEMPLARS + FLOOR — the habitat note proposes what's missing):
1. **Parametric enumeration** — list what you already know (seeds). Biased toward famous/recent —
   that's fine, it's one modality, and the corpus adjudicates it.
2. **Citation expansion** — `asta literature snowball` (backward/forward/citances) + co-citation
   pooling from the seeds' cached edges. Bounded by citation reachability; can't reach forward in
   time from old seeds and can't leave the seeds' community.
3. **Survey-reference pooling** — the reference lists of surveys/reviews of the area: an
   enumeration INDEPENDENT of your seeds. Works cited by ≥2 surveys are the high-confidence slice.
4. **Gap-directed sweeps** — wherever an independent modality exposes a weak slice (a region, a
   language, a subdomain, an era), run targeted searches for that slice specifically.
5. **Forward citations** for recency (new items citing the captured hubs).
Expect title-search name-collisions in sweeps — curation strips them; judge the paper, not the query.

## 2. Convergence: cross-modality yield, not zero-count
- A fresh independent modality returning mostly-new items = NOT converged (low inter-modality
  overlap means the population is under-sampled). Keep adding modalities until a new one yields
  little new. Track the share of items found by ONLY ONE modality — high single-modality share is
  the under-sampling smell.
- Within a modality: stop when the DISTRIBUTION (family shape) stops shifting, not when raw yield
  hits zero — a same-shaped tail is more-of-the-same, not new coverage.

## 3. Estimate what's missing (the [T] signals; `scripts/coverage_signals.py`)
- **Capture-recapture across modalities** (`capture_recapture_modalities`): treat two capture
  occasions → Chapman estimate. CALIBRATED usage: pair the PF-FILTERED group against the
  FILTER-INDEPENDENT group (best usable estimate; still ~20% low). NEVER pair two independent
  modalities against each other — they co-capture the same famous canon and N̂ collapses (the
  deeper shared latent is citation FAME, which no lineage split removes). Heterogeneous
  catchability makes every variant a LOWER bound — say so; on disjoint catchments the
  reliability gate fires and no re-slice helps (that class needs exposure/rejected data).
- **Many-occasion Chao1 on real citation incidence** (`unseen_class_incidence`) for the
  backward axis. GATE: label_coverage < 1 ⇒ lower bound; judge every capture (relevance-as-you-go).
- **STRATIFY, never quote a flat "% missing"** (`reference_pool_recall`): recall by
  citation-frequency threshold over what the core collectively cites. A healthy mature corpus is
  ~100% at ≥3 core-citations with misses only in the singly-cited periphery — "canonical
  literature complete; the estimated tail is peripheral" is a very different (and usually true)
  statement than "X% missing".
- **Signals disagreeing is diagnostic, not noise** — locate why (a truncation, a label gap, a
  modality hole) before averaging anything.

## 4. Recall anchors (you can't prove completeness from inside the set)
- **Known-canon check**: enumerate the area's canon parametrically → `knowledge.anchor()` — the
  corpus adjudicates (present? judged how?). OFFLINE-first: anchors are usually already in the
  store. A low recall-to-relevant with high judged-out is deliberate exclusion, NOT a miss.
- **Survey-reference recall**: what fraction of a scope-matched survey's references did you see?
  Only the never-seen slice is a candidate gap.
- Related-Work reading of a few central papers adds framing/understanding and catches
  non-indexed items (tech reports/blogs) — it rarely changes coverage; the aggregate
  reference-pool already covers that signal offline.

**Two anchor moves that two independent runs evolved unprompted — adopt as named moves:**
- **Infrastructure-adjusted reference-pool recall**: when raw reference-pool recall looks low,
  enumerate the TOP never-captured co-cited hubs and CLASSIFY each (foundation models, datasets,
  optimizers, retrievers = out-of-scope substrate). If ~90% of high-frequency never-seen nodes
  are substrate, the depressed recall is an artifact and the boundary is validated; the residue
  is your real gap list.
- **External-enumeration anchor**: resolve a maintained community list/registry against the
  corpus and report BOTH resolve-rate and %-into-core. Calibration receipt: academic-only
  modalities captured just 38% of a maintained community roster on one thread — the list was the
  detector, and absorbing it was the fix.

## 5. Localize gaps, prioritize closure
- `citation_graph` missed-high-centrality: uncaptured nodes many core papers cite — TRIAGE
  in-scope canon vs out-of-scope famous hubs (they're usually hubs). The triage is a KIND/SCOPE
  judgment, so automate it with a cheap-tier LLM classification of the never-seen titles
  (infra/benchmark/method-of-the-field vs candidate in-scope work), NOT with a citation-ratio
  score: `gap_lift` (local/log-global) was calibrated against a real hand triage and scored
  AUC 0.50 — chance — because the field's own infrastructure is maximally thread-specific yet
  out-of-scope. Use gap_lift only as a presentation order (mega-hubs sink); never as the triager.
- **Relevance-weighted eigenvector centrality** (`eigenvector_centrality`) = the validated
  ranking prior for which candidates to judge/acquire next (top-decile ~80% relevant). Keep the
  weight binary; feed the cached edges.
- Closing the peripheral tail needs NON-citation modalities (semantic/venue/author sweeps) — more
  snowball only re-reaches the same neighborhood.
- **Shadow signals beyond citations** (each relation sees a different missing population):
  **mention-shadow sweep (VALIDATED)** — invert the mentioned-entities extraction field against
  the corpus name universe; rank mention-dangling entities by doc-frequency and judge the head
  (caught a real run's #1 named gap at 12 mentions, plus misses even the gold union shared;
  verify every flag against corpus+gold before claiming — a normalization bug false-flagged an
  in-corpus item). **Dangling-lineage (pass-gate)**: extends-graph parents ∉ corpus should be
  EMPTY — non-empty is a loud alarm; empty licenses only "lineage closed", it cannot detect
  comparison-class misses.

## 6. The verdict (the [J] step — yours)
Triangulate: discard signals that fail their self-check; ensemble surviving estimators into a
RANGE; let convergence + anchors modulate confidence; output captured / estimate / confidence /
ranked gaps / boundary. State what a user should and should not conclude from the corpus. If the
population grows continuously (active fields), say "complete as-of" and name the refresh trigger.
**Calibrated claim shape (leave-one-out calibration across 3 independent runs of one thread —
every verdict tested was OVERCONFIDENT, none underconfident; correct for the bias structurally):**
- Claim the HEAD and the TAIL separately: canon-anchor licenses "~85–95% of the highly-cited
  stratum captured" and NOTHING about the tail — beyond the head, say "the corpus SAMPLES the
  tail; it does not enumerate it." Chao1-style lower bounds were the only calibrated estimator —
  prefer "at least X missing" over point estimates.
- PROPAGATE the single-modality-share smell into the claimed range (it was the best early-warning
  signal in calibration and was ignored by the verdict numbers it should have widened).
- Reference-pool recall is self-referential (blind to sub-communities the core doesn't cite) —
  never let it stand without an EXTERNAL anchor (enumeration/maintained list).
- Name two loss terms estimators can't see: **ingestion loss** (judged-relevant papers that never
  entered the rings — check it) and **scope drift** (state the exact file+count the verdict was
  computed over; recompute after the last data change).
- **The anchoring rule (measured failure: a verdict claimed 85-90% head; external truth measured
  ~44%):** a CR/lower-bound point estimate may NEVER anchor the "missing" number — write the
  bound AS a bound and let the smells widen it. Any head claim ≥ "most of the head captured"
  requires an anchor EXTERNAL to the run's own enumeration culture (accumulated gold, a
  maintained list, a registry) — a self-enumerated seed canon shares your sweeps' blind spot and
  anchors nothing.
- **Truncation term (REQUIRED — the data is already in your sidecars/origins):** per modality,
  state the binding cuts: exhausted-N-of-N vs truncated-N-of-M (total_hits), and the un-escalated
  remainder of the sweep policy. A measured run left ~9,500 unjudged drop-events (~6-12%
  relevant) unmentioned because it never read its own sidecars.
- **Venue/list-enumeration completeness:** any venue or curated list you enumerated gets an
  explicit year-range/entry-count completeness assertion against the source (a run enumerated a
  workshop 2018-2024 while the source listed 2025 too — the machinery never flagged the missing
  year; it was caught only by external audit).
- The cheapest calibrator of all is a second independent run — for high-stakes threads, say so.
- **Report coverage as a FAMILY × ERA MATRIX, not a scalar** (calibrated: misses concentrate —
  top cells held 40–56% of true misses in ~20% of coverage; scalars hide exactly this). The two
  validated INTERNAL flags are **era-dips** and **empty cells**; deeper hole-detection needs an
  EXTERNAL per-cell volume prior (self-consistent holes look healthy from inside — do not claim
  the matrix's quiet cells are covered).
Verdict discipline (each learned from a real run):
- **Name your estimators — including the gated ones.** The verdict lists every estimator
  considered and its status (used / GATED: why). A silently skipped estimator is
  indistinguishable from a forgotten one; "Chao1 gated: external-ref label coverage 0.08" is
  itself coverage information. `report()` emits this scaffold.
- **Recompute AFTER the last data change.** Gap-closure rounds change the strata; a verdict
  computed mid-run and shipped after more closure misreports recall (stale-report bug).
- **Deferred slices get a DERIVED residual.** If you triage (judge the ≥k-frequency slice, defer
  the rest), estimate the deferred slice's relevant count by extrapolating the yield-vs-frequency
  GRADIENT of the judged strata (`yield_by_frequency`) — e.g. yields 45%/38%/27% at freq 4/3/2
  extrapolate to ~15–20% at freq 1. Show the derivation, not a gut number.
- **CR across modalities needs co-capture.** Modalities with disjoint catchments (different
  eras/communities) give tiny overlap and an absurd N̂ — the `reliable=False` gate discards it;
  say so in the verdict rather than averaging it in.
- **Completeness critic (fresh eyes, cheap) before finalizing:** spawn a FRESH-context subagent
  given only the question + a corpus summary + the modalities used, prompted adversarially:
  "what would a resourceful human do that this pipeline didn't? what chunk could be missing?"
  Every signal above is computed from INSIDE your catchments; the critic is the only one that can
  point at a library you never visited. Its output = candidate gaps to check, not verdict overrides.
