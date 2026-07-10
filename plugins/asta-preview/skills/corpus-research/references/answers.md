# Answers — grounded, trust-carrying, right-altitude

Answers are extracted/synthesized from the substrate, grounded in sources, and each carries its
own trust story. Output is a revisable artifact, not a final pronouncement.

## Every answer carries a "How performed" note — HARD requirement
Append to each answered sub-question a short note: **corpus + ring used + method (tag-tally vs
per-paper extraction vs aggregation) + evidence tier (abstract / full-text / snippet-grounded) +
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
