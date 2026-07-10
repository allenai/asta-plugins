# Worker contract — fan-out subagents (judging / tagging / extraction / synthesis)

Canonized from 232 workers across five measured runs. The deepest lesson: **prompt sentences do
not change worker behavior; structure does.** A run carried the strongest "append immediately,
never buffer" instruction yet written — every judge still buffered, and when a spend limit
killed the fleet, 8 shards died with zero lines on disk (~344 judgments re-paid). Encode
expectations as task structure and [T] checks, not as requests.

## Build shards with `scripts/shards.py` (structure does the enforcing)
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
