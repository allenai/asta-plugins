# Data discipline — provenance, gates, and a run MANIFEST

On long analyses, trust dies quietly: artifacts pile up, a quality drop hides in a catch-all
bucket, nobody can tell what's current vs obsolete or what produced a number. These practices make
gaps POP and keep lineage answerable. (This is where working-with-Claude on long research most
often fails — treat it as first-priority, not bookkeeping.)

## Stage-coverage gates (generalize label_coverage to EVERY stage)
Every stage reports a coverage/quality number and REFUSES to feed downstream when it's low:
- relevance label_coverage · **tag_coverage** (real-family, not Other/untagged) · extraction
  coverage + evidence-grounding · evidence-depth mix.
- `substrate.py`'s TAG_GATE refuses downstream reads until it passes (threshold lives in substrate.py + codebook.md).
- **Never let a quality drop hide in a real category.** Split "Other" into genuine-unclassifiable
  vs untagged/low-confidence. A ballooning "Other" is a gate failure, not a finding.

## Provenance on every record
- Candidates carry `provenance` = the acquisition modalities that found them (also powers
  corroboration + capture-recapture).
- Tags/judgments are applied as ORDERED batches (filename order, last-write-wins) with per-record
  `tag_batch` / `resolution` — so any label traces to the batch that set it.
- Extractions carry `evidence_span`, `evidence_depth`, `confidence`, `extractor_batch`.

## Run MANIFEST.md (the lineage ledger)
Keep `<run>/MANIFEST.md` answering "what ran on what, current vs obsolete":
- Each artifact: role (CANONICAL source-of-truth vs DERIVED regenerable), producer (script/step +
  when), inputs + coverage, status (current / superseded / obsolete).
- CANONICAL = raw judgments/tags/opencode, the codebook (@vN), acquisition provenance, thread.json.
  DERIVED = standardized-relevance.jsonl, observations.jsonl (rebuild, never hand-edit).
- Log INCIDENTS (e.g. a mis-tagged batch, truncated abstracts reused for extraction) with the fix —
  the manifest is where a silent corruption becomes visible.

## Verify lineage from ground truth — never guess
Before computing on data, confirm what it actually is (which batch, which tier, which evidence
tier). Guessing at data lineage is a top failure mode; a wrong assumption about the data silently
poisons every number downstream.
