# Curation — relevance judgment as common currency

Turn candidates into a graded, provenanced collection. Relevance is the run's common currency:
one schema across retrieval scores, judge verdicts, adjudications, audits.

## The standardized judgment (write to `<run>/judgments/<NN>-<resolution>.jsonl`)
`{corpusId, tier: in|relevant|maybe|not-relevant, criteria: [{criterion, grade 0-3}], judged_by,
  reason, <axis>_guess fields (open codes — one guess field per axis of YOUR thread's criteria;
  derive the names from thread.json, don't copy another thread's), evidence_quote, scope_note}`
- Grade EACH thread.json criterion 0–3; the tier is your holistic call across criteria.
- Filename order = authority order (retrieval-judged < single-judge < panel < audit); later
  overrides earlier. `scripts/relevance.py` normalizes them into standardized-relevance.jsonl.

**The 0–3 grade rubric (per criterion) — this is the shared currency; make the same call every
time.** Deliberately the paper-finder 4-level scale, so grades are comparable across
retrieval-judged / Claude-judged / audited records and across runs:
- **3 — perfectly meets this criterion.** Squarely, unambiguously what the criterion asks for.
- **2 — highly relevant.** Clearly meets it, with a minor caveat (partial coverage, adjacent framing).
- **1 — somewhat relevant.** Touches the criterion tangentially / in passing; a stretch to count.
- **0 — not relevant.** Does not meet this criterion.
Grade against the criterion's `definition` in thread.json, NOT against overall vibe — a paper can
be 3 on one criterion and 0 on another. The `reason` + `evidence_quote` must justify a ≥2.

**tier = the holistic verdict across criteria** (which ring the paper lands in):
- **in** — core: meets the thread's relevance bar decisively (typically 3 on the primary criteria).
- **relevant** — belongs, but lighter (a 2, or abstract-only judged) — the candidate ring.
- **maybe** — genuinely borderline; surface these at the post-curation beat, don't silently decide.
- **not-relevant** — out (name-collision, off-thread, wrong modality) — one-line reason required.
Grade→tier is a JUDGMENT [J], not an arithmetic threshold — but if you find yourself calling a
straight-1 paper "in", say why in the reason.

## Judge-and-open-code in ONE pass (do this — don't re-read abstracts per stage)
The judge must also emit **light open codes**: the thread-shaped "what does it analyze / by what
method" phrases (whatever your criteria hinge on), a one-line reason, and a short VERBATIM
`evidence_quote`. **Verbatim means verbatim** — copy the span exactly; elide with "..." (each
fragment exact), never condense in your own words (audited: judge-time quotes ran ~93% verbatim
with light paraphrase the main deviation — the quote is the judgment's audit trail). Three payoffs: (1) one abstract-read serves judging AND seeds the codebook's
open codes (grounded coding starts from these); (2) it makes grading HONEST — the criteria hinge
on exactly these fields, and a judge that cannot name the phenomenon cannot justify a high grade
(nullable extraction IS the relevance test, countering inclusion bias); (3) the quote makes the
judgment auditable. KEEP IT LIGHT: open-code phrases + quote only — full extraction (findings,
claims, spans per sub-question) stays post-curation, on the relevant ring, at the evidence tier.

## Cost-tier the judging (don't panel everything — validated ordering)
1. **Corroboration pre-filter** (near-free): candidates found by ≥2 acquisition modalities are
   very likely relevant — light-touch them.
2. **Single abstract judge** for the bulk — matches a body+panel gold ~95%+ on clear cases.
3. **Panel (3 judges) + body-text + adjudicator WITH REASONING** — reserve for the genuine
   borderline only. Use an adjudicator that reads each judge's reasoning, not bare majority vote.
   (A lone judge GIVEN body text can do WORSE than on the abstract — query-conditioned snippets
   mislead without cross-check; escalate to body only inside the panel.)

## Graduated judging for large candidate pools (designed from measured runs)
When the judged tail is big (typically ~60% of judging spend goes to rejects), don't judge in
arrival order and don't defer all-or-nothing at the end:
1. **Prior-ordered queue ([T], free):** order candidates by the priors you already hold —
   retrieval relevanceScore, corroboration count, the relevance-weighted centrality prior
   (`coverage_signals.eigenvector_centrality`; top-decile ~80% relevant). Judge descending and
   track **yield-by-prior-decile** as you go: the defer/continue call becomes a data-driven
   mid-stream decision on the marginal-yield curve (honestly reportable), and anything deferred
   gets its derived residual from the same curve.
2. **Cheap-first cascade (model tiering):** a screening pass on a cheap model three-ways the pool
   (clear-in / clear-out / uncertain); the strong model judges only the uncertain band.
   **Calibration is non-negotiable:** before trusting the cheap tier, measure its agreement
   against the strong tier on a sample of THIS thread; adjudication/escalation always strong-tier.
   Mechanical stages (tagging, chart data) go to the cheapest tier; extraction needs a tier that
   preserves VERBATIM quotes — verify it doesn't paraphrase before delegating.

## Evidence: reuse snippets, escalate deliberately
- `asta literature` returns snippets/contexts — KEEP them on the candidate; judge on
  abstract+snippet, not title alone (title-only drops are a systematic false-negative source).
- Criterion-targeted snippet search (1 call/paper) sharpens the method/finding locus; PDF/full
  text only for the non-open / empty-abstract residual.

## Strip search noise, expose scope creep
- Name-collision hits from targeted sweeps (a physics paper matching a model's name, a benchmark
  matching a technique) → not-relevant with a one-line reason.
- Extraction reads deepest and will flag scope leaks the relevance judge missed (off-thread
  systems, wrong modality) → feed those to `<run>/scope-exclusions.json` so they're out in the
  substrate everywhere, not filtered ad-hoc per query.

## Hygiene (learned the hard way)
corpusIds are STRINGS everywhere; sanity-check set operations (audit∩seeds, ∩collection) before
trusting counts — a mixed int/str subtraction silently corrupts leak measurements.
