# Deliverables — answers doctrine + report spec (read BOTH at the deliverable phase)

## Part A — answers (grounding + method notes + links)

Answers are extracted/synthesized from the substrate, grounded in sources, and each carries its
own trust story. Output is a revisable artifact, not a final pronouncement.

**Machinery stays backstage (user call, measured against a run whose prose read "round-X /
job-X"):** user-facing prose leads with findings and speaks the USER's vocabulary; internal
unit names (rounds, jobs, shards, waves, gates) belong in the contract artifacts and method
notes, not the narrative. The method note names the method, not the machinery's filing system.
Findings first; artifacts listed compactly at the end.

## Every answer carries a "How performed" note — HARD requirement
Append to each answered sub-question a short note: **corpus + ring used + method (tag-tally vs
per-paper extraction vs aggregation) + evidence depth (abstract / full-text / snippet-grounded) +
the key limit/gate.** Reuse the gate outputs you already computed — surface them per-answer, don't
bury them. Trust is built per-answer, in place, not only in a separate methods section. A skeptical
reader trusts a number when they can see how it was derived and what its limits are.
**A single global "based on N papers" header does NOT satisfy this** — the note is per answered
sub-question.

## Every answer carries a FRAME line — HARD requirement (rides the how-performed note)
The frame = **view + version + denominator**: which declared view/ring the number was computed
over, under which tier_map/charter version, over how many members ("charter core under map v3,
n=479"). Rings are DERIVED views (SKILL step 0); an answer that reaches outside the default
view SAYS so here. Absence-flavored answers state their SEARCH SCOPE in the same line
("not found in <scope>" vs "does not exist" — vault.md interrogation conventions).

## Q-responsiveness — answer the question AS ASKED (HARD)
The deliverable answers the user's question in its own terms. When the honest answer requires a
SUBSTITUTION — a distribution where a field-level question was asked, a proxy where the asked
quantity isn't extractable — the substitution is STATED as one, IN the answer, not silently
performed (measured: a report answered field-shaped questions with per-paper distributions and
never said so). Absence-honesty applies to substitutions exactly as to missing papers: "you
asked X; the corpus supports X′; here is X′ and why" is a legitimate answer — an unmarked swap
is not.

## Paper links — HARD requirement
Every paper reference in a user-facing artifact is a WORKING link — a bare corpusId is dead text;
readers must reach the paper in one click (the user touches the sources). Default:
`https://api.semanticscholar.org/CorpusId:<corpusId>`. When the work isn't on S2 (blog posts,
tech reports, some theses), link whatever canonical page exists — arXiv, DOI, publisher, the
post itself. Any working link beats a perfect-format dead one.

## Declare the ring
Say which ring an answer runs over: `core` (fully curated — the conservative read) vs
`core+candidate` (broad coverage, lightly-judged — say so). The coverage/precision trade-off is
explicit, chosen, and stated — never an ad-hoc per-query set.

## Ground in sources; keep the user connected
Route evidence by where the answer lives (Q1/counts from tags; findings/direction from abstracts;
verbatim claims/disagreements from body snippets). Hand the user verbatim spans + pointers into
papers, not only your synthesis.

## "Disagreement / controversy" questions (a specific, easy-to-get-wrong shape)
**Candidate axes must not be mined from the positive core alone (3rd recurrence of this miss —
measured: a real spanning axis — intervention identifiability — was invisible to positives-only
mining because its partisan papers sat judged-out/DISPUTED at the charter boundary, while peer
reviews of core papers carried it loudly):** generate candidates from the core PLUS the
adjacent/judged-out/DISPUTED ring and any available review/critique register (`scripts/reviews.py`
fetches the OpenReview register for hosted venues — a stratum, not the population), PLUS one
**open lens** for extractor-invented axes at a LOWERED candidacy floor — an axis nobody seeded
may still be real; let extraction propose it, and let the support gate (which still governs what
gets CLAIMED) sort it out. Every shipped axis carries an explicit **seeded-vs-discovered
label** (measured: a run's 9 surviving axes were exactly its 9 seeded candidates — readers must
see that the mining never discovered anything).
The value is the FEW MAJOR axes the field is split on — spanning MANY papers with real support on
BOTH sides — NOT one-vs-two-paper spats (a 30-vs-1 split is consensus with an outlier — classify
it, below, don't fake a controversy from it).
1. Pool oppositions ACROSS content-families into field-level axes (don't enumerate per-family spats).
2. **Inclusion gates on evidence quality, never on share.** A side qualifies with ≥2 papers at
   strength ≥ the declared floor (strength-v1 below; stretch-fit rows never count toward the
   floor). Share then CLASSIFIES the axis — every included axis ships labeled as one of:
   **contested** (both sides qualify and neither dwarfs the other; requires spanning ≥2
   sub-areas) · **consensus-with-credible-dissent** (a qualifying minority against a much
   larger majority — surfaced AS dissent with its evidence and per-side counts, never presented
   as "the field is split") · **consensus-with-outlier** (minority fails the quality floor —
   one line, kept visible). Single-paper dissent with exceptional warrant is surfaceable,
   flagged single-source. Axes failing inclusion are LISTED with their shape — never silently
   dropped. The classification is a VIEW over the stance rows (measured: share-relative floors
   demote the field's most-studied axis at any realistic depth — a 21-paper, 88-quote minority
   was demoted at 19.6%<25%, and every axis demoted in a shallow run flipped or strengthened
   when a deeper run re-measured it).
3. The DEEPEST disagreements are often methodological and need a SYNTHESIS pass over the finding
   text (not just direction-tag counting) — surface them explicitly with supporting corpusIds.
4. **Ground each side per-paper (proven pattern):** at extraction time, record `positions` =
   {axis, stance, VERBATIM quote} per contested axis per paper — the per-side counts become
   auditable claims, not tag tallies. Then [T]-aggregate the stances into a tally file BEFORE
   the [J] synthesis agent runs, so the synthesis quotes numbers it didn't compute.

### Evidence STRENGTH v1 (the composed view behind the gate's floor)
strength-v1 is a DECLARED VIEW (versioned, sliceable — it names its frame like any view),
COMPOSED from signals every stance row already carries; nothing new is invented at extraction
time: **fit** (explicit/rephrased/reframed/stretch — the warrant contract, evidence.md) ×
**evidence tier** (basis.source_tier: fulltext/abstract) × **source stratum** (S1 peer-reviewed /
S2 preprint / S3 non-indexed) × **validation grade** where the claim is method-shaped
(validated-isolated / validated-endtoend / described / proposed — a standard lens, not a
one-off). Reference strong predicate: explicit-or-rephrased fit ∧ fulltext ∧ (validated-* when
method-shaped); the exact predicate set is DECLARED at build and calibrated before the gate
reads it — a floor that the corpus's best-evidenced minority side fails is miscalibrated, not
evidence against the minority. Every axis record ships a **PER-SIDE STRENGTH PROFILE**: the
reader sees not just how many papers per side, but how solid each side's evidence is.
**Two axes, kept distinct:** strength-v1 measures INTERNAL material strength — what the claim
rests on inside the paper (fit, tier, validation, plus the row's `support_kind` +
`strength_note`, evidence.md). EXTERNAL source quality — signals about the SOURCE, external to
the claim — joins the per-side profile only as CONTEXT LABELS from existing metadata: stratum
(the v0 ladder) and citation counts (an acceptance proxy, already in candidates metadata).
Zero new extraction cost, never disqualifiers. Author/team reputation is explicitly DEFERRED —
author disambiguation is measured-unreliable, and reputation is exactly the prestige trap the
guardrail below exists for.
**Prestige guardrail (user ruling):** strength must NOT collapse into venue prestige — the
not-yet-popular good work is often S2 preprints. Stratum is a LABEL/slice in the profile,
NEVER a disqualifier; fit + tier + validation carry the floor. (The measured direction agrees:
S2 escalates VERIFICATION sooner — trust≠relevance, and trust≠exclusion.)
At synthesis the profile rides with the per-side `support_kind` mix and the rows'
`strength_note`s (synthesis pass, item 3b) — all inputs the synthesis judge WEIGHS; none is
ever aggregated into a score.

## The SYNTHESIS PASS — NO POOLED CLAIM SHIPS UN-RE-READ (HARD)
A **pooled claim** is any claim whose basis is a SET of other rows — any aggregate derived over
a view (codebook families, disagreement axes, distributions, trends, comparisons) AND
syntheses-over-syntheses (a report narrative pooling family claims). Counting locally-assigned
labels is not synthesis, and the counting script structurally cannot see conditional claims
(measured, a real axis re-read: 8 rows filed "mixed" were EXCLUDED from the shipped 52-vs-8
count, and two of them were the strongest evidence in the pool — the best-supported claim was
CONDITIONAL on architecture and task difficulty and never surfaced).
Before any pooled claim ships, re-read its basis set and run the audit:
1. **Fit-mix audit** — decompose the count by fit strata (explicit/rephrased/reframed/stretch/
   legacy-unwarranted; see references/evidence.md): "26% address X" becomes per-fit strata.
2. **Confound hunt** — do the sides partly measure their instruments? (measured: circuit-
   discovery methods are built to find sparse subgraphs, probing methods test full-vector
   decodability — the axis's sides partly measured their tools). Is the pooled quantity
   conflated ("localized-of-WHAT": neurons/heads/circuits/features/layers)?
3. **REWRITE the pooled claim with its own because + unless** — both clauses are mandatory on
   pooled claims (measured: that is where the warrant pays). But because/unless is RECORD
   register, not narrative register: the reader's paragraph LEADS with the finding; the warrant
   audit lives in the collapsed block/sidecar. A narrative sentence >~400 chars carrying
   "because…unless…" is the measured smell of record register leaking into prose.
3b. **The re-read WEIGHS, not counts (the systematic-review model: consolidating many results
   into one stronger claim means weighting each piece by what it actually rests on).** The
   re-read GATHERS each basis row's `strength_note` — the notes are what it reads to weigh,
   and the weighing discussion happens over the notes + `support_kind`s + external context
   labels together. The pooled claim's rewrite states its SUPPORT COMPOSITION from the rows'
   `basis.support_kind` ("3 own-experiments + 12 position-assertions", never "15 papers"),
   and the because records HOW the mix was weighed — why the 3 carry it, or why they don't.
   Disagreement-axis verdicts state the PER-SIDE support-kind mix alongside the strength
   profile: a side of 4 own-experiments can outweigh a side of 20 assertions, and the
   classification (contested / dissent) may follow the weighing, not the headcount. NO
   mechanical score aggregation — strength-v1, support_kind, and the notes are INPUTS the
   synthesis judge weighs; the weighing decision itself lands in because/unless
   (reasoning-first: the nuance is the judge's, the signal is the contract's), and the unless
   names the weighing's escape ("unless the 3 experiments share a confound / the assertions
   trace to independent labs").
4. **Ejections are DISPUTED marks** on the offending rows — never deletions (append-only).
Fires on ALL shipped pooled claims (user ruling: even a surviving axis gained load-bearing
conditions; risk-tiering data insufficient to skip safely — revisit after N runs). The pass may
unilaterally DISPUTE rows; tier/membership changes stay panel work. Budget: ~$1-3/pooled claim
at the cheap-capable tier (measured: $0.9 for a 60-row axis, verdict YES-conditions-added);
report-scale ≈ $15-40, funded by the extraction rebalance, not additive.
**The pass leaves a MECHANICAL record — `report/data/synthesis.json`:** one entry per shipped
pooled claim `{claim, because, unless, basis_note}`; every family/axis stat surfaced in
keystats/charts must have an entry. `report_gate.py` FAILS a report whose sidecar is missing or
whose surfaced stats lack entries (measured: a run's keystats were gate-gamed while its pass
lived only in prose) — this file is where the doctrine above becomes checkable.
No placeholder fields: a sidecar field ships POPULATED or is omitted — an empty/all-zero field
emitted to satisfy a schema reads as data (measured: a shipped fit_mix field was all-zero
placeholder in every entry).
**The pass gets its own second layer:** the synthesis pass EDITS claims and can introduce
errors of its own — after it runs, cross-check the RENDERED output against the data files
(numbers in prose/charts vs sidecar entries) before shipping (measured: a synthesis pass itself
introduced an inconsistency; the rendered-report check was what caught it).
**Unsynthesized pools:** an answer over a pool that never had its pass SAYS SO in the method
note and offers the pass (~$2) — never presents a raw count as a synthesized finding.

## Aggregation altitude
Group/count at the altitude the question asks (families, not raw strings; techniques deduped by
model-family; findings by phenomenon). Make groupings revisable on request ("redo those groups").
Aggregate PER-STRATUM when thread.json declares `scope.strata` (the pooling rule lives at
SKILL step 0).
**empty≠other (twice-ruled):** null/unprocessed is a SEPARATE class in EVERY aggregate and
chart — never folded into "Other" (measured: a run shipped Other=20 while its own synthesis
entry said 7+13 — the missing class was unprocessed rows). An "Other" that mixes judged-other
with never-processed misstates both, and no shipped aggregate may contradict its own synthesis
entry.
**Singleton-tail policy:** open-code singletons ("other:<phrase>" rows) get an explicit
disposition at aggregation — fold into an existing family, promote (on ≥2 recurrences), or ship
as a LABELED singleton tail with its n; never a silent catch-all bucket (measured: 96 "other:"
singletons rode into a report unexamined).

## Part B — the REPORT (shape + content requirements)

Disambiguation (three things people conflate):
- **Report** = THE user-facing browsable deliverable. One entry point, self-contained, portable.
  It is a FILE first (markdown set + an HTML explorer) — packageable, emailable, re-sendable.
- **Run artifacts** = workspace files (candidates, judgments, substrate, caches). Never shown AS
  the deliverable; the report LINKS INTO them ("every number traces to a file you can open").
- **Delivery is part of the report (measured: calling the hosted page "optional" cost two
  rounds their links).** When the ask is sharing-shaped ("show my team lead", "send a
  colleague"), the report SHIPS as a deployed hosted page: deploy, hand the user the URL, and
  record the URL in the round-manifest/MANIFEST — a report is not "presented" until the user
  holds a working link. The package must work OUTSIDE this machine: no links into local
  workspace paths (bundle the standing report in when layering an update). The report gate
  applies to UPDATES exactly as to first builds. The hosted page is the publishing channel
  only — do NOT source the report's structure from generic artifact-design guidance; this
  file is the spec.
- **Cost-actual at close (MANDATORY — two runs closed without it and their cost claims were
  ungradable; a third read this paragraph and still skipped the number — so it is now
  GATE-CHECKED, not just doctrine).** TWO carriers, both required: (1) the close MESSAGE
  states what the run consumed (fleet subagent count + model tier, cost as tokens×price; or
  the subscription-lane form: turns + subagents + fetch counts + "compute tokens eval-side");
  (2) the round-manifest carries a STRUCTURED `cost_actual` field in the same form —
  report_gate.py check 5 FAILS the report without it. An estimate labeled as an estimate is
  fine; prose-only is not.

## Living reports — layering an update (measured pattern, adopt it)
When updating a standing report (new rounds since it shipped): ONE page serves both readers —
a **changelog block** up top (what changed, when, by which round) + **NEW badges** on added
findings and **standing badges** where unchanged material carries fresh corroboration; the
standing report is BUNDLED into the package (not linked across the filesystem) so first-time
readers get one coherent report and returning readers find additions at a glance. Flag stale
items rather than silently re-deriving them. The report gate runs on the update like any build.
**Consolidation-completeness:** a page claiming to REPLACE prior reports diffs its section
coverage against them before shipping — still-standing content moves IN, or the replacement
claim NARROWS (measured: a consolidating page left the axes set, the product table, and the
full catalog standing only under SUPERSEDED banners while claiming to replace them). A reader
following "this supersedes X" must never need X for content the new page silently dropped.

## Content requirements (each traces to a real reader complaint or a real run's win)
1. **One index page / README**: what this is, corpus size + as-of date + refresh trigger, links
   to every deliverable, a read-order, and honest notes. Readers start here.
2. **Per-question method notes** + 3. **working links** — the two HARD requirements from Part A
   above apply to every report page.
4. **Evidence in the body — REPORT PROSE CARRIES SPANS.** When the ask says "extract the
   paragraphs/passages", the verbatim spans appear IN the report (linked to source), never only
   in data files. A reader who asked for paragraphs and finds tallies experienced an omission,
   whatever the data files contain. And the rule binds the NARRATIVE, not just embeds
   (measured: a report's 86.8% verbatim-surface rate was carried by dumping the catalog into a
   CSV + a JS blob while its narrative prose contained ZERO verbatim extracted content — the
   prose a reader actually reads touched no sources). The readable prose itself quotes spans.
5. **Per-paper catalog view** grouped by the derived families, with tier/tags and a one-line
   grounded claim per paper — the view readers use to judge the corpus itself.
6. **Honest coverage section**: verdict + estimators-used-vs-gated + explicit boundary + "what
   not to assume." Numbers trace to the coverage files.
7. **Distribution visuals per deliverable, data-generated.** Each question's view opens with its
   distribution(s) — family/tier breakdowns, per-axis stance splits (both sides, with n),
   modality yields on the coverage page. Charts are GENERATED from the data files (a script →
   chart-data JSON → inline SVG), never hand-coded numbers — charts are where numbers silently
   drift from data. Each chart captioned with what it counts and its n. In-section panels, not a
   separate charts layer.
8. **Self-contained rendering**: no external CDNs/scripts/fonts; everything inline. Works
   offline, works emailed, works on any hosted channel.
9. **The package**: report + final data files (observations / extractions / relevance + a CSV
   for spreadsheet readers) + README with read-order and honest caveats — the package is what
   actually gets SENT.
10. **Engagement is a feature** — interactive embeds (sortable catalog, filters, expandable
    evidence) are worth their cost IF grounded in the data files; a browsable report is what
    non-operators actually read.
11. **Every prose aggregate has a data-file home.** Any count/percentage quoted in report prose
    must exist in a shipped data file (ship the aggregate you quote; coverage-verdict numbers
    live in coverage files). Audited: a real report's per-family adoption counts existed only in
    prose — untraceable = unreviewable. `report_trace`-style checking should find ~0 orphans.
12. **Rendering honesty (each clause measured on a shipped report):** promised affordances must
    EXIST — "sortable" shipped without sorting is a broken promise; ship the affordance or drop
    the adjective · no mid-word truncation anywhere (truncate at word boundaries, with an
    ellipsis) · catch-all families are NEVER listed first (ordering is a claim about importance;
    lead with the substantive families) · single-page reports over ~30k visible chars carry NAV (a table of contents /
    jump links — a long page without one is unscannable) · where the catalog data carries a
    headline-finding column, the rendered view surfaces it.
