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
**Candidate axes must not be mined from the positive core alone (measured: a real spanning
axis — intervention identifiability — was invisible to positives-only mining because its
partisan papers sat judged-out/DISPUTED at the charter boundary, while peer reviews of core
papers carried it loudly):** generate candidates from the core PLUS the adjacent/judged-out
ring and any available review/critique register (`scripts/reviews.py` fetches the OpenReview
register for hosted venues — a stratum, not the population); the support gate still governs
what gets CLAIMED as an axis.
The value is the FEW MAJOR axes the field is split on — spanning MANY papers with real support on
BOTH sides — NOT one-vs-two-paper spats, and NOT lopsided near-consensus (a 30-vs-1 split is
consensus with an outlier, exclude it).
1. Pool oppositions ACROSS content-families into field-level axes (don't enumerate per-family spats).
2. Support-gate: keep an axis only if the minority side has real support (floor: ≥2-3 papers with verbatim quotes AND ≥~25% of the axis's cited papers — two runs' axes at ≥2/side replicated each other independently; uncontested axes are findings, not disagreements) and
   it spans ≥2 sub-areas.
3. The DEEPEST disagreements are often methodological and need a SYNTHESIS pass over the finding
   text (not just direction-tag counting) — surface them explicitly with supporting corpusIds.
4. **Ground each side per-paper (proven pattern):** at extraction time, record `positions` =
   {axis, stance, VERBATIM quote} per contested axis per paper — the per-side counts become
   auditable claims, not tag tallies. Then [T]-aggregate the stances into a tally file BEFORE
   the [J] synthesis agent runs, so the synthesis quotes numbers it didn't compute.

## Aggregation altitude
Group/count at the altitude the question asks (families, not raw strings; techniques deduped by
model-family; findings by phenomenon). Make groupings revisable on request ("redo those groups").
Aggregate PER-STRATUM when thread.json declares `scope.strata` (the pooling rule lives at
SKILL step 0).

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
  ungradable).** The close message states what the run actually consumed: fleet
  subagent count + model tier, and cost as tokens×price (or "subscription lane, N subagents,
  ~X M output tokens" when not API-billed). An estimate labeled as an estimate is fine;
  silence is not — the user is owed the bill next to the deliverable.

## Living reports — layering an update (measured pattern, adopt it)
When updating a standing report (new rounds since it shipped): ONE page serves both readers —
a **changelog block** up top (what changed, when, by which round) + **NEW badges** on added
findings and **standing badges** where unchanged material carries fresh corroboration; the
standing report is BUNDLED into the package (not linked across the filesystem) so first-time
readers get one coherent report and returning readers find additions at a glance. Flag stale
items rather than silently re-deriving them. The report gate runs on the update like any build.

## Content requirements (each traces to a real reader complaint or a real run's win)
1. **One index page / README**: what this is, corpus size + as-of date + refresh trigger, links
   to every deliverable, a read-order, and honest notes. Readers start here.
2. **Per-question method notes** + 3. **working links** — the two HARD requirements from Part A
   above apply to every report page.
4. **Evidence in the body.** When the ask says "extract the paragraphs/passages", the verbatim
   spans appear IN the report (linked to source), never only in data files. A reader who asked
   for paragraphs and finds tallies experienced an omission, whatever the data files contain.
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
