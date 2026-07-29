# Evidence records — the extraction contract (warrants, grounding, absence)

Why this contract exists (the founding incident): an extraction record read `stopping:
{addressed: true, mechanism: "…learn when to invoke retrieval…"}` — the extractor honestly
described an INVOCATION mechanism and still checked the stopping box, because the schema
offered a bare boolean and no field where "why does this count?" had to be justified. The
force-fit shipped into a family count and took three investigations to diagnose instead of
one lookup. Measured across the pipeline that produced it: ~50:1 per-paper extraction vs
cross-paper synthesis; a schema census found 7 bare-boolean fields carrying ~7,721 values —
the force-fit surface. This file is the fix at the RECORD grain; the pooled-claim fix is the
synthesis pass (deliverables.md); the cross-round index is vault.md.

## The row (one per claim-instance)
```
{corpusId · round · lens (a NAMED view, per the thread's registry) ·
 claim_type: finding|stance|classification|entity-mention   (stances/axis-sides ARE claims) ·
 polarity: present|absent                                   (absence is a CLAIM, never a silent
                                                             null/dropped field) ·
 claim: kind-typed fields                                   (NO bare booleans) ·
 basis: {span: VERBATIM, source_tier: abstract|fulltext|snippet,
         support_kind: own-experiment|own-ablation|benchmark-result|qualitative-analysis|
                       theoretical-argument|citation-to-other-work|position-assertion|
                       other:<specific>                          (suggested vocab, not a closed
                                                                  enum — semantics below),
         strength_note: 1-2 free-text sentences                  (the weighing nuance — below),
         validation: validated-isolated|validated-endtoend|
                     described|proposed                          (OPTIONAL — method-shaped
                                                                  claims only; below)} ·
 scope_flag · because · unless · fit · judged_by · confidence}
```
- **Pointer is COMPUTED BY SCRIPT, never LLM-emitted.** The extractor's only grounding duty is
  the verbatim span; `vault.py rebuild` computes the verification RUNG (ladder in vault.md;
  offset/section columns are forward work — not yet stored, do not claim them). Span-not-found
  at rebuild = flagged `unverified`, counted loudly. Zero new extractor friction.
- **Kind-typed fields, no bare booleans.** `addressed: true` is the measured force-fit
  invitation — replace with a kind enum (e.g. stopping: invoke|continue|terminate|budget|
  abstain) so the record must SAY what kind of thing it found, and the warrant says why it
  counts.

## REASONING-FIRST emission order (the contract, not a style choice)
Warrant fields are EMITTED in this order: **because → unless → fit → confidence** — reasoning
before judgment, so the clauses behave as reasoning, not post-hoc rationalization. Measured
(A/B on the same 18 rows against a hidden independent key): judgment-last ordering moved every
grade that moved TOWARD the key, sharpened force-fit separation to 5/5 stretch, and made the
skip-unless-on-explicit behavior vanish (unless fill 18/18 vs 16/18) at identical cost.
Fit-honesty 80% strict / 93% under the lenient read, vs 80% strict for judgment-first.

## Field semantics
- **fit** (self-graded): `explicit` (the paper says it in its own words) · `rephrased` (other
  words) · `reframed` (asserted under OUR lens — the legitimate new-lens class) · `stretch`
  (honest guess flag). Measured honesty: ZERO force-fits passed as explicit/rephrased in
  either A/B arm — the failure mode the field exists to catch had zero occurrences.
- **because** — one sentence: why the basis supports the claim UNDER THE LENS. ALWAYS written;
  trivially short on explicit (the friction lands exactly on the inference; explicit pays
  ~nothing).
- **unless** — one clause: what would disqualify the claim. ALWAYS written. The quality bar is
  specific-and-checkable ("check whether the Evaluator's completeness judgment is actually
  consumed by the agent in real time"), never boilerplate. MANDATORY on pooled claims —
  measured: that is where it pays.
- **confidence** — 0-2 (2 = the source clearly settles it; the same scale the application
  rules consume: confidence-2 rows apply, ≤1 stays proposed/triaged). It is CONSUMED at the round-close/merge
  contract (vault.md round contract: confidence-2 rows apply; ≤1 enters proposed/triaged) —
  the measured failure this repairs: 227 stored scores read by no gate, calibration ignored.
- **basis.source_tier** — abstract|fulltext|snippet; the regression gate (vault.md) compares
  tiers across rounds, so record it honestly.
- **basis.support_kind** — what the paper itself offers BEHIND the claim: own-experiment ·
  own-ablation · benchmark-result · qualitative-analysis · theoretical-argument ·
  citation-to-other-work · position-assertion. A SUGGESTED vocabulary, not a closed enum —
  the open-coding escape (`other: <specific>`) is legitimate; the vocabulary grows bottom-up
  like the codebook and gets reviewed at close under the singleton-tail policy
  (deliverables.md aggregation altitude) — primitives over schemas. Judged from the span's
  context at extraction time, same grain as because/unless; EXTRACTION RECORDS ONLY (judgment
  rows stay light — the overwork boundary holds). This is the study-design axis of GRADE-style
  evidence hierarchies in generic form; synthesis consumes it as a weighing input
  (deliverables.md synthesis pass), never as a score to aggregate.
- **basis.validation** (OPTIONAL; method-shaped claims only) — does the paper VALIDATE the
  mechanism/criterion it claims, and how: validated-isolated (an experiment isolates the
  claimed component) · validated-endtoend (works inside a system, component not isolated) ·
  described (specified, never tested) · proposed (suggested only) — plus the open escape.
  Absent on non-method claims. Extraction records only, same grain as support_kind. This is
  the standard lens the strength view's third clause reads (strength.py): without it, a
  method-shaped position paper at fulltext/explicit-fit grades strong.
- **basis.strength_note** — the nuance carrier: one or two FREE-TEXT sentences distilling what
  matters for WEIGHING this evidence — scale/n, models/conditions covered, controls or their
  absence, directness to the claim, the caveat the authors themselves state. What a systematic
  reviewer jots in the margin. Same writing convention as because/unless: ALWAYS written,
  trivially short when there is little to say. Distinct role from `because` (because = why the
  span supports the claim; strength_note = how strong/limited the underlying evidence is).
  Extraction-record grain only; the synthesis pass's re-read GATHERS these notes — they are
  what it weighs over.

## Absence claims (polarity=absent)
"Paper does NOT do X" is a first-class row: polarity=absent + **basis showing what the paper
does INSTEAD** (the verbatim span of the alternative mechanism), because = why that alternative
isn't X under the lens, unless = what evidence would flip it. Measured: absence rows coherent
under this shape in both pilots that wrote them (3/3, 2/2). Never encode absence as a silent
null or an unchecked boolean — absence needs polarity IN the row. The interrogation-side twin
("not found in <scope>" vs "does not exist") lives in vault.md's conventions.

## Scope (user-ruled, P3-narrow)
Warrants attach to EXTRACTION RECORDS and POOLED/FAMILY-LEVEL SYNTHESIS CLAIMS — not to every
conversational answer (the per-answer "How performed" note already covers answer grain; avoid
ceremony). User may widen later.

## Cost + legacy
Measured live under this schema: ~18.5k tok/paper vs ~22k for the old judging — PARITY, and the
new records carry 2-5 warranted claims vs 2 grades. Legacy rows (pre-contract) enter the
evidence index as `fit=legacy-unwarranted` (measured load: 3,378 records across 5 threads);
backfill is TARGETED only (regression-flagged papers + user-named families), never bulk.
