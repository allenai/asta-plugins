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

## Build shards with `scripts/shards.py` (structure does the enforcing)
- **SALTS ARE A GATE**: `build_shards` now REFUSES to build an unsalted fleet (measured: a
  warm round's hand-rolled shards silently dropped salts and lost per-judge calibration).
  Deliberate exceptions declare `allow_unsalted="<reason>"`, recorded in salts.json.
- **Stratified-interleave assignment**: shards are exchangeable samples of the pool, so
  per-shard positive-rate spread becomes a judge-drift ALARM instead of composition noise
  (measured spreads of 4-87% across shards were unreadable without this).
- **Salt items**: ~5 known-gold items (clear-in / clear-out / boundary) injected per judge
  shard, indistinguishable in-shard; the mapping lives in `salts.json` OUTSIDE the shard.
  `score_salt()` grades each shard's judge: strictness, boundary-agreement, maybe-discipline —
  drift alarms with evidence, re-judge triggers, and free tier-calibration data.
- **k-chunked emission, enforced**: shard files are divided into sub-batches (~25). The worker
  prompt template processes ONE sub-batch per emission — judge 25, append 25, verify count,
  next. This is the structural fix for the buffering attractor (extractors' k≈6 read/append
  loop survived every interruption; single-pass judges lost everything).

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
