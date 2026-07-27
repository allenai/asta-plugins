# Worker contract — fan-out subagents (judging / tagging / extraction / synthesis)

Canonized from 232 workers across five measured runs. The deepest lesson: **prompt sentences do
not change worker behavior; structure does.** A run carried the strongest "append immediately,
never buffer" instruction yet written — every judge still buffered, and when a spend limit
killed the fleet, 8 shards died with zero lines on disk (~344 judgments re-paid). Encode
expectations as task structure and [T] checks, not as requests.

## Fleet MODEL TIER (measured at three levels — a DEFAULT with override, not a mandate)
Judge/worker fleets default to the **cheap-capable tier (sonnet-class)**; main-loop synthesis
stays on the strong model. Measured on the same gold ruler: sonnet fleet vs opus fleet showed
**no quality difference at any level** (aggregate recall parity · both passed salt gates ·
row-level disagreement arbitration a statistical tie, 23-26 of 49) while the opus fleet cost
~5× per fleet token — the single largest uncontrolled cost variable found across runs ($387 vs
$132 for the same build). The salt/canary gates are the quality guard (fired correctly in both
directions: rejected a haiku fleet, passed sonnet and opus fleets). Override deliberately when
a fleet task genuinely needs the strong model — and record the override in the round record.

## RECIPES — sharding + panel assembly (patterns, with the gate at MERGE)
Note: the retained `shards.py` convenience ALSO hard-refuses unsalted fleets at build time
(belt-and-suspenders; SystemExit). A deliberate unsalted exception uses validate.py's
`allow_unsalted` with a RECORDED reason — the merge gate is the boundary that counts.
Why recipes, not mandated scripts (measured, then user-ruled): per-round orchestration
conveniences get RE-DERIVED — sessions hand-rolled sharding and panel assembly repeatedly,
documentation notwithstanding — and the one gate that rode INSIDE a convenience (the salt gate
inside shards.py) is exactly the one that kept getting silently lost (a warm round's hand-rolled
shards dropped salts; a headless round re-implemented sharding and the gate never fired). Ruling:
gates fire at OUTPUT BOUNDARIES, never inside conveniences. So compose the recipes context-fitted
or use `scripts/shards.py` (a CONVENIENCE that builds them for you) — either way **the trust
boundary fires at MERGE: `validate.py`'s fleet-output check (judgments present + salts present
OR an `allow_unsalted="<reason>"` recorded), regardless of how the shards were built.**
Re-promotion rule: a recipe graduates back to a maintained script after 2 independent
re-inventions converge (how sweep.py earned canon).

### The SHARDING recipe (these elements ARE the recipe, however you build the files)
- **Stratified-interleave assignment**: shards are exchangeable samples of the pool, so
  per-shard positive-rate spread becomes a judge-drift ALARM instead of composition noise
  (measured spreads of 4-87% across shards were unreadable without this).
- **Salt items**: ~5 known-gold items (clear-in / clear-out / boundary) injected per judge
  shard, indistinguishable in-shard; the mapping lives in `salts.json` OUTSIDE the shard.
  `shards.py score` grades each shard's judge: strictness, boundary-agreement, maybe-discipline —
  drift alarms with evidence, re-judge triggers, and free tier-calibration data. An unsalted
  fleet loses per-judge calibration silently — hence the merge gate.
- **k-chunked emission**: shard files are divided into sub-batches (~25). The worker
  prompt template processes ONE sub-batch per emission — judge 25, append 25, verify count,
  next. This is the structural fix for the buffering attractor (extractors' k≈6 read/append
  loop survived every interruption; single-pass judges lost everything).

### The PANEL-ASSEMBLY recipe (the genuine-borderline slice; curation.md owns WHEN)
- 3 independent judges (fresh contexts, body text available, same shard structure as any
  fleet — sub-batches, per-line `judged_by`) + an ADJUDICATOR that reads each judge's
  REASONING — never bare majority vote. Escalate to body text only inside the panel (a lone
  judge given body text can do WORSE than on the abstract).
- **Merge gate**: the panel's merged output passes the same `validate.py` fleet-output check —
  judgments present per assignment, salts or a declared exception, per-line lineage. A panel
  merged without the gate is a hand-rolled fleet with its calibration silently lost (the
  measured failure this section exists to prevent).

## The worker prompt contract (every fan-out prompt carries ALL of these)
1. Inputs by PATH (rubric file + shard file); per-paper bodies by `digest_path` — NEVER inline
   full text in a batch file (a run's 350KB inline batches broke Read and spawned chaos).
2. Sub-batch emission protocol (above) + idempotent resume: on start, read the output file,
   skip present ids.
3. Machine-parseable finish line ONLY ("done: <n> + tier tally"); never paste results back.
4. Per-line lineage: every output record carries `judged_by: "<wave-tag>"`.
5. **Do NOT spawn subagents** (26 leaf workers across runs forked expensively before this line
   existed anywhere).
6. On a failing validation script: READ the traceback before rerunning (a judge reran an
   identical failure 6×).
7. `evidence_quote` MANDATORY on judgments — verbatim; a run that skipped quotes at judge time
   paid for it at every later adjudication.
8. EXTRACTION packets carry the evidence-record contract VERBATIM (workers never read
   references — the packet is the only surface they see; measured: a warm round whose packets
   lacked it shipped 32 adjudication rows with zero warrant fields). Every record:
   `{corpusId · round · lens · claim_type: finding|stance|classification|entity-mention ·
   polarity: present|absent · claim: kind-typed fields, NO bare booleans · basis: {span:
   VERBATIM, source_tier: abstract|fulltext|snippet} · scope_flag · because · unless ·
   fit: explicit|rephrased|reframed|stretch · judged_by · confidence: 0-2}` — warrant fields
   EMITTED reasoning-first (because → unless → fit → confidence); absence claims are rows too
   (polarity=absent + a basis span showing what the paper does INSTEAD). Field semantics:
   `references/evidence.md` — YOU read it before writing the packet (SKILL.md step 6 MUST).

## Fleet mechanics
- **Probe-canary first**: run ONE worker per operation ~5 min ahead; inspect its output file
  shape + a few records; only then fan out. Stagger launches (3 → rest).
- Spend-limit deaths hit ~15-18% of workers in measured runs: sub-batch emission makes them
  cheap (resume from the last append); plan reruns into the schedule, don't be surprised.
- Model tier: bulk = the cheap strong tier; calibrate anything cheaper against salt items on
  THIS thread before trusting it (never assume transfer).
- Synthesis workers (disagreement axes etc.): support-gated prompt — ≥2 papers with verbatim
  quotes per side, reject uncontested axes, self-validate the gate before writing output.

## Anti-patterns (each observed, each expensive)
one giant Write at the end · results held in context across sub-batches · multi-shard workers
(3×90 in one context drifts) · inline fulltext in shards · leaf workers spawning helpers ·
blind retry loops · quotes deferred to "later".


## Waiting on a fleet (canonical loop — measured: every session re-derived this, several hit
the blocked-foreground-sleep error first)
Foreground `sleep` chains are blocked by the harness. Wait with an until-loop on the OUTPUT
files, checking both existence and expected line count:
```
until [ -f <run>/judgments/shard-07.jsonl ] && [ $(wc -l < <run>/judgments/shard-07.jsonl) -ge 158 ]; do sleep 15; done
```
For many shards, one background waiter over the set beats per-shard polls. After the wait,
ALWAYS run the completeness check (shards.py) — a worker stopping one sub-batch early is a
measured failure mode; recover the missing ids with a small single-judge tail, don't re-run
the shard.

## Worker scratch is PER-WORKER (measured collision: one worker's scratch file was overwritten
mid-run by a sibling targeting a different shard)
Workers write intermediate/scratch files ONLY under <run>/scratch/<worker-id>/ (the shard name
serves as the id). Shared locations are for the protocol outputs the packet names — nothing else.
