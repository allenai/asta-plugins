# Curation — relevance judgment as common currency

Turn candidates into a graded, provenanced collection. Relevance is the run's common currency:
one schema across retrieval scores, judge verdicts, adjudications, audits.

## The standardized judgment (write to `<run>/judgments/<NN>-<resolution>.jsonl`)
`{corpusId, tier: in|relevant|maybe|not-relevant, criteria: [{criterion, grade 0-3}], judged_by,
  reason, ability_guess/method_guess (thread-shaped open codes), evidence_quote, scope_note}`
- Grade EACH thread.json criterion 0–3; the tier is your holistic call across criteria.
- Filename order = authority order (retrieval-judged < single-judge < panel < audit); later
  overrides earlier. `scripts/relevance.py` normalizes them into standardized-relevance.jsonl.

## Judge-and-open-code in ONE pass (do this — don't re-read abstracts per stage)
The judge must also emit **light open codes**: the thread-shaped "what does it analyze / by what
method" phrases (whatever your criteria hinge on), a one-line reason, and a short VERBATIM
`evidence_quote`. Three payoffs: (1) one abstract-read serves judging AND seeds the codebook's
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
