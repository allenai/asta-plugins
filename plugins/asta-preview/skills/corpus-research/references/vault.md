# Vaults — how a corpus thread accumulates knowledge across rounds

A VAULT is a corpus thread's persistent knowledge store: the canonical records of every prior
round (verbatim), a derived union view, and fetch-once caches. It is what turns one-shot corpus
runs into a LONG-RUNNING research thread: later rounds start warm, corroborate earlier
judgments, and leave structure the next round can trust. Measured receipts: rounds working from
a vault manifest alone executed the full round contract 4-for-4; cross-round re-judging created
the first 2× corroboration tier; warm answer rounds cost ~5-10% of a cold corpus build.

**The boundary is NOT sessions.** A ROUND is a unit of work with its own charter and as-of date
— a follow-up question batch an hour later in the SAME session is a round exactly as much as a
fresh session weeks later. The vault line is: knowledge that must be trusted LATER, without
re-derivation, by a reader who didn't watch it being made — and a single long session crosses
that line too (context gets compacted; in-context "memory" of a judgment decays into an
unverifiable claim; the agent that extracted a fact 20 hours ago is effectively a prior round).
So graduate a run to a vault when its FIRST round closes (coverage verdict + answers shipped)
and the thread continues in any form — same session included. Everything below (append-only
records, trust marks, the round contract, the closing rebuild) applies within one session
identically: prose you remember is inherited; only what's re-verified against records is
verified.

## Layout (what `scripts/vault.py` builds and maintains)
```
vault/
  VAULT-MANIFEST.md     the covenant: what exists, trust marks, the round contract (template below)
  vault.json            machine-readable: rounds registry (id, source, as_of, note), layer stats.
                        COUNTS AND FRESHNESS LIVE HERE, not in manifest prose (prose goes stale).
  rounds/<id>/          each round's canonical record VERBATIM: thread.json (charter),
                        standardized-relevance.jsonl, observations/extractions, coverage verdict,
                        round-manifest.json. Schemas may DIFFER by round — deliberately not
                        normalized (primitives over schemas; the consumer controls joins).
  view/union.jsonl      one row per paper ever judged: per-round tiers side by side + agreement
                        (agreed-positive / agreed-negative / DISPUTED) + n_rounds_judged + trust
                        mark. THE default query surface (same core fields as knowledge.py's
                        collection view — the vault IS that view, persisted and growing).
  cache/                fulltext-cache/ + s2-cache/, merged across rounds. Fetch-once.
  QUESTIONS.log         the question stream (asked / answered-by / spawned-by) — append-only;
                        itself vault knowledge.
```

## The growth model (what may change and how — this is the whole integrity story)
- **Canonical records are APPEND-ONLY.** A round adds `rounds/<its-id>/`; it NEVER edits a prior
  round's files. Trust marks mean nothing if history can be rewritten.
- **Caches are append-only fold-back — and this binds SUBAGENTS.** Every external fetch (main
  agent or worker) deposits into `cache/` before use. A worker that fetches full texts and keeps
  them in its own context has broken fetch-once (measured failure: a round's fetched PDFs were
  lost because the fold-back rule didn't name subagents).
- **Derived layers are never hand-edited.** `view/union.jsonl` and `vault.json` are rebuilt
  mechanically — `python scripts/vault.py rebuild <workspace>` — as the ROUND'S OWN closing
  step. No human maintainer in the loop; the derivation is deterministic and auditable.
- Hand-written vault files a round touches: `QUESTIONS.log` (append) and the MANIFEST's
  narrative prose (a round MAY update the freshness note / header story — that's covenant
  text, not derived data; counts NEVER go in prose, they live in vault.json).

## The eval boundary (audited 2026-07-12; state it precisely)
A thread's OWN ground truth (its gold rows, adjudications, calibration docs) never enters that
thread's vault — that would let the corpus grade itself. Eval-side MEASUREMENTS about tools,
methods, or OTHER corpora are admissible as [external] evidence in a vault's question log,
attributed like any published result. Questions routed from the eval side carry their source
label ("eval-side probe") — attribution is part of the record.

## Trust marks (thread-side facts only — no external gold enters a vault)
- `agreed-positive/N×` with N≥2 — independent rounds with different charters converged. The
  strongest claim a vault makes. Reliable, not infallible.
- `agreed-*/1×` — a single round's uncontested call. A claim, not a verification.
- `DISPUTED` — rounds genuinely disagreed (usually charter-boundary differences; one thread's
  audit measured 85% of its hard conflicts as charter-maturity artifacts). Never silently pick
  a side: if a disputed paper matters to your question, judge it against YOUR charter and
  record that as a new opinion (that's how disputes resolve — by more opinions, not edits).
- `DISPUTED-resolved:<tier>/<round>` — the mechanical resolution overlay (`resolved_latest` in
  the view): set when the NEWEST opinion postdates an already-existing conflict among older
  rounds — a deliberate re-judge of a known dispute, or a later round's fresh call under the
  matured charter. The dispute history is never erased (agreement stays DISPUTED,
  tiers_by_round keeps every opinion); this is the thread's CURRENT call. Only row-backed
  re-judges count — a resolution argued in prose resolves nothing.
- **Inherited ≠ verified.** Anything stated from the vault carries its mark; anything you
  re-judge, re-extract, or fresh-sweep yourself upgrades it — and a verification that lives
  only in prose upgrades NOTHING: write it to `trust-upgrades.jsonl` (schema below).

## Operating clause (how to work within a vault)
1. The vault is your FIRST capture occasion, never the population. Query the view before any
   external call; every fetch folds back into the caches.
2. Separate inherited from verified in every coverage claim and answer.
3. The vault shares the blind spots of the rounds that built it (shared retrieval culture, an
   era, its charters' exclusions — each verdict names its holes; read them). New external
   anchors beat another pass over the vault.
4. Extend, don't fork — and CLOSE YOUR ROUND (the contract).

## THE ROUND CONTRACT (prose answers are welcome; STRUCTURE is what compounds)
Before finishing, a round leaves, under `round-<id>/` in the workspace:
1. `round-manifest.json` — charter, as-of date, questions asked/answered/spawned, files
   produced, what was verified vs inherited, method notes per question.
2. Any NEW or RE-JUDGED papers as `standardized-relevance.jsonl` rows — same schema as prior
   rounds (per-criterion 0-3 grades, stratum, text_source, title). Where prior rounds' rows
   predate a field the curation doctrine now requires (e.g. title), curation.md WINS — add the
   field rather than matching old rows' omissions. This is how the vault grows.
3. `trust-upgrades.jsonl` — every claim re-verified this round, durably:
   `{corpusId, claim, from_mark, to_mark, evidence_span, method}`.
4. Appends to `vault/QUESTIONS.log`.
4b. **Answer-invalidation check (corpus-changing rounds only; measured: a round tripled a
   family while the deployed report still said "thin"):** diff what your round changed against
   the STANDING answers and any deployed report — refresh what your delta touched (redeploy
   same-URL) or flag it in QUESTIONS.log. The report's own "refresh trigger" line IS this
   obligation; a corpus-changing round is the trigger firing.
5. **Deliverable gate (measured to decay when left to memory — this line is the durable
   trigger):** before building OR UPDATING any user-facing report, re-read deliverables.md and
   run `report_gate.py` to PASS; sharing-shaped asks ship DEPLOYED with the URL recorded in
   the round-manifest.
6. **The closing rebuild**: `python scripts/vault.py rebuild <workspace>` — folds the round in,
   advances the vault's as-of. Verify the printed counts moved as expected. Post-close fixes
   to the LATEST round: re-run with `--amend <round-id>` (refreshes its canonical copy;
   earlier rounds stay immutable).

**Deferral-with-declaration (a named right-sizing move — measured: a 1,381-candidate
forward-cite tail deferred cleanly):** when a question surfaces acquisition-scale work
mid-round, CACHE the candidates, DECLARE the deferral (thread.json / round-manifest), and
spawn it into QUESTIONS.log as its own future round — never silently judge a tail the round
wasn't scoped for, never silently drop it.

Round TYPES share this contract and differ only in gates: an ANSWER round (a few questions,
targeted retrieval) adds rows in the handful range and must not regress to memory-only answers;
an ACQUISITION round (new sweep) runs the full pipeline gates (SKILL.md steps 1-6); an AUDIT
round (re-judge a slice, fulltext-verify) is measured by trust-upgrades produced. Scale the
machinery to the question shape — a 2-question answer round with the stack in targeted mode
measured ~2× a skill-less baseline's cost, not 20×.

Vocabulary, precisely: **the FIRST corpus build is round 1** — a finished run's canonical
closing state already satisfies this contract, which is why `vault.py init` folds it in
verbatim as the founding round. And rounds ≠ BEATS: a round is a knowledge-lifecycle unit
(charter in → contract out → folds into the vault); a beat (SKILL.md interaction cadence) is a
user-contact point WITHIN a round where state is surfaced for steering. Beats communicate,
rounds compound; a beat may END a round early, but the close is still the contract.

## Warm-workspace setup (the binding — do this when a thread goes long-running)
Skill triggers cannot see that a fresh session is a continuation. The workspace carries it:
the workspace `CLAUDE.md` names this skill ("research rounds use the corpus-research skill —
invoke it at round start"), names the retrieval stack, and says "read vault/VAULT-MANIFEST.md
before acting". Measured: this one paragraph is what made the treatment round load the skill;
without it, rounds run on base ability and the manifest alone.

## VAULT-MANIFEST.md template (adapt; keep it ~1 page)
```
# VAULT — <thread topic>
You are working WITHIN an accumulated research vault: <founding round, date, charter owner>
plus <answer/audit rounds folded in>. Read this manifest before anything else.
## What's here            <the Layout section above, instantiated; counts → "see vault.json">
## Trust marks            <the marks above + any round-specific caveats (e.g. "r2 has no
                           evidence quotes"; "r1 +relevant slice is abstract-judged")>
## Freshness              complete as-of <date, per vault.json>; this field moves in <weeks|
                           months> — for recency-sensitive questions sweep forward first.
## Operating clause       <the four points + THE ROUND CONTRACT, verbatim from this reference>
```

## Creating a vault from a finished run
`python scripts/vault.py init <workspace> --from <run_dir>` copies the run's canonical files in
as the founding round, builds caches/view/vault.json, and drops the manifest template for you
to instantiate. Then write the workspace CLAUDE.md binding (above) and the thread is warm.
