# Example theorizer mission statement

This is a worked example of the **mission statement** passed to the theorizer in the
`theorizer_theories` node of the `data_driven_theory_generation` template. It is not the
run's `mission.md`; it is the prompt the theorizer receives once the per-theme
reproductions have settled, distilled from `scope.question`, the curated AutoDS laws,
and the per-theme findings.

A well-formed theorizer mission does five things, and this example shows all five:

1. **States the question** in one sentence, naming the phenomenon and the population of interest.
2. **Lists the settled empirical findings** (`E*`) that any returned theory must explain, each tagged with the experiment / AutoDS law that established it so the theory stays anchored.
3. **Lists the open questions** (`Q*`) the theories should address — the gaps reproduction left unresolved.
4. **States the constraints** (`C*`) — framings already *refuted* by reproduction, so the theorizer does not regenerate them.
5. **States the rewarded framings** (`R*`) — the mechanistic shapes worth pursuing, anchored back on the laws the run actually reproduced.

Tagging each finding/question/constraint with its supporting experiment is what keeps
the returned theories anchorable: downstream, `theorizer_theories` drops any theory
without ≥1 law anchor, and this structure makes the anchor explicit.

---

```
Mission: Generate theories that explain the role of populations aged 5+ years in
Pakistan's 2022-2024 WPV1 resurgence, anchored on the following settled empirical
findings and the open questions they leave unresolved.

SETTLED EMPIRICAL FINDINGS (must be explained by any theory):
  E1. National Pol3 coverage stopped predicting national WPV1 cases around 2018-2019
      (T1 retry-2, p=0.0005; AutoDS L1 cross-cutting).
  E2. Pakistan and Afghanistan annual WPV1 case counts are coupled, with the coupling
      strengthening significantly after 2021 (X2).
  E3. At the 2022-2024 district level, WPV1 case counts are still positively predicted
      by under-5 population share, with under-5 share dominating 15-64 working-age
      share (T2 retry-1).
  E4. Among districts with both WPV1 and cVDPV2 in 2019-2021, cVDPV2 (not WPV1)
      dominates in adult-heavy districts (X4, p<0.001).
  E5. BCG-Pol3 dropout does not outperform Pol3 alone as a predictor at any tested
      scale (T5 retry-0/1).
  E6. Border-adjacency adds explanatory power for WPV1 cases only in the post-2021
      window (X6, p=0.079); resident Afghan refugee stock does not predict WPV1
      (X7).

OPEN QUESTIONS (theories should address at least one):
  Q1. What replaced national Pol3 coverage as the dominant transmission lever
      after 2018-2019?
  Q2. What specific mobility FLOW (returnees, deportations, transits) post-2021
      drives the case coupling intensification?
  Q3. Why does the subtype demographic contrast (cVDPV2 in adult districts, WPV1
      in young districts) appear?
  Q4. How do older (>5y) populations contribute to WPV1 transmission given that
      they are NOT the dominant district-level predictor but ARE plausibly the
      operative mobility vectors?

CONSTRAINTS (refuted framings to avoid):
  C1. Theories framing Pol3 as "merely a health-system access proxy" — refuted at
      district level by T1 retry-1 (LR p=0.0021 rejects dropping Pol3).
  C2. Theories framing the >5y cohort as the dominant transmission reservoir —
      refuted at district by T2, at province by T2 retry-4, on silent-transmission
      signature by X3, and on subtype contrast by X4.
  C3. Theories grounded primarily in BCG-Pol3 or Penta1-Measles dropout — refuted
      by T5 retry-0/1.
  C4. Theories centered on resident Afghan refugee populations as a static mobility
      channel — refuted by X7.

REWARDED FRAMINGS:
  R1. Theories that explain the 2018-2019 break date in terms of immunological,
      programmatic, or product-transition (tOPV→bOPV April 2016) mechanisms.
  R2. Theories that articulate FLOW-based mobility mechanisms (returnees,
      deportations, seasonal transit) consistent with the post-2021 intensification.
  R3. Theories that reconcile the subtype contrast (X4): a single coherent biological
      / immunological story explaining why cVDPV2 emerges in adult-heavy settings
      while WPV1 retains a pediatric profile.
  R4. Theories that integrate older (>5y) populations as mobility VECTORS (carriers)
      rather than primary RESERVOIRS, consistent with E2, E3, and E6.
  R5. Theories that explicitly anchor on AutoDS L1 (temporal decoupling) and L4
      (mobility) — the two laws DV reproduced.
```
