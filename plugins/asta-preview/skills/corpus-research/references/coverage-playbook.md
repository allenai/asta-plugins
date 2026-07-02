# Coverage playbook — honest, quantified comprehensiveness

Goal: a coverage VERDICT you can defend — `{captured, missing-estimate range, confidence, ranked
gaps, explicit boundary}` — never a bare "comprehensive" and never a single scalar.

## 1. Multi-modal acquisition (the only honest way in)
Run INDEPENDENT modalities, each blind to the others, tagging every candidate with its modality:
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
- **Capture-recapture across modalities** (`capture_recapture_modalities`): treat two independent
  modality groups as capture occasions → Chapman population estimate. Heterogeneous catchability
  (famous items over-captured) makes it a LOWER bound — say so.
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

## 5. Localize gaps, prioritize closure
- `citation_graph` missed-high-centrality: uncaptured nodes many core papers cite — TRIAGE
  in-scope canon vs out-of-scope famous hubs (they're usually hubs).
- **Relevance-weighted eigenvector centrality** (`eigenvector_centrality`) = the validated
  ranking prior for which candidates to judge/acquire next (top-decile ~80% relevant). Keep the
  weight binary; feed the cached edges.
- Closing the peripheral tail needs NON-citation modalities (semantic/venue/author sweeps) — more
  snowball only re-reaches the same neighborhood.

## 6. The verdict (the [J] step — yours)
Triangulate: discard signals that fail their self-check; ensemble surviving estimators into a
RANGE; let convergence + anchors modulate confidence; output captured / estimate / confidence /
ranked gaps / boundary. State what a user should and should not conclude from the corpus. If the
population grows continuously (active fields), say "complete as-of" and name the refresh trigger.
