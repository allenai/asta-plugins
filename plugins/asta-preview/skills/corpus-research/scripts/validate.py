"""validate.py — run-integrity GATE: machine-checked invariants after EVERY merge/rebuild.

Why this exists (learned twice in one run): merges silently lose invariants, and the failure
modes anomaly-noticing can't catch are the dangerous ones. Count reconciliation caught a
judged-but-never-merged orphan; it CANNOT catch a provenance-union regression (counts stay
perfect while the contents rot — corroboration and capture-recapture inputs silently corrupt).
Run this after every candidates-merge / substrate rebuild. Non-zero exit = STOP and fix before
any downstream step.

Checks:
  1. corpusId is a STRING everywhere (int/str mixing silently corrupts set ops).
  2. No duplicate corpusIds within candidates / observations / standardized-relevance.
  3. observations ≡ candidates (same id set).
  4. every judged id ∈ candidates (no judged-but-never-merged orphans).
  5. candidates ⊇ every acquisition modality file (MERGE COMPLETENESS — the opt-in source-list
     bug). Files matching *-all.jsonl / *-raw.jsonl / *.log are treated as raw/unscreened and
     skipped; list deliberate deferrals in thread.json "acq_deferred": ["file.jsonl", ...] —
     deferral must be DECLARED, never silent.
  6. PROVENANCE UNION: every id present in ≥2 modality files carries ≥2 provenance tags on its
     candidate record.
  7. ring ↔ tier consistency (not-relevant→out; unjudged tier→unjudged ring).
  8. Report (not gate): label-coverage, tag-coverage over the relevant set.

Usage: python validate.py <run-dir>          (exit 0 = all gates pass)
"""
from __future__ import annotations
import glob, json, os, re, sys
from collections import Counter

RAW_MARKERS = ("-all.jsonl", "-raw.jsonl", ".raw.")


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


def validate(run):
    failures, warnings = [], []
    cfg = json.load(open(os.path.join(run, "thread.json"))) if os.path.exists(os.path.join(run, "thread.json")) else {}
    deferred = set(cfg.get("acq_deferred", []))

    cand_rows = jl(os.path.join(run, "candidates.jsonl"))
    obs_rows = jl(os.path.join(run, "observations.jsonl"))
    rel_rows = jl(os.path.join(run, "standardized-relevance.jsonl"))

    # 1. string ids everywhere
    for name, rows in (("candidates", cand_rows), ("observations", obs_rows),
                       ("standardized-relevance", rel_rows)):
        bad = [r.get("corpusId") for r in rows if not isinstance(r.get("corpusId"), str)]
        if bad:
            failures.append(f"[ids] {len(bad)} NON-STRING corpusIds in {name} e.g. {bad[:3]}")

    ids = lambda rows: [str(r["corpusId"]) for r in rows]
    cand, obs, rel = set(ids(cand_rows)), set(ids(obs_rows)), set(ids(rel_rows))

    # 2. dupes
    for name, rows in (("candidates", cand_rows), ("observations", obs_rows),
                       ("standardized-relevance", rel_rows)):
        d = [c for c, n in Counter(ids(rows)).items() if n > 1]
        if d:
            failures.append(f"[dupes] {len(d)} duplicate ids in {name} e.g. {d[:3]}")

    # 3. observations ≡ candidates
    if obs and cand != obs:
        failures.append(f"[sync] candidates≠observations: only-cand {len(cand - obs)}, only-obs {len(obs - cand)}")

    # 4. judged ⊆ candidates
    judged = set()
    for p in glob.glob(os.path.join(run, "judgments", "*.jsonl")):
        judged |= set(str(r["corpusId"]) for r in jl(p))
    orphans = judged - cand
    if orphans:
        failures.append(f"[orphans] {len(orphans)} judged ids NOT in candidates (judged-but-never-merged) e.g. {sorted(orphans)[:3]}")

    # 5. merge completeness + 6. provenance union
    mods = {}
    for p in sorted(glob.glob(os.path.join(run, "acq", "*.jsonl"))):
        b = os.path.basename(p)
        if any(m in b for m in RAW_MARKERS):
            continue
        if b in deferred:
            warnings.append(f"[deferred] acq/{b} declared deferred in thread.json — excluded from completeness")
            continue
        rows = jl(p)
        if not rows or "provenance" not in rows[0]:   # modality files carry provenance; other
            continue                                   # working files in acq/ are not gated
        mods[b] = set(str(r["corpusId"]) for r in rows)
    for b, s in mods.items():
        lost = s - cand
        if lost:
            failures.append(f"[merge-loss] {len(lost)} ids from acq/{b} missing from candidates "
                            f"(declare in thread.json acq_deferred if deliberate) e.g. {sorted(lost)[:3]}")
    crec = {str(r["corpusId"]): r for r in cand_rows}
    multi = [c for c in set().union(*mods.values()) if sum(c in s for s in mods.values()) >= 2] if mods else []
    bad_prov = [c for c in multi if c in crec and len(set(crec[c].get("provenance") or [])) < 2]
    if bad_prov:
        failures.append(f"[provenance-union] {len(bad_prov)}/{len(multi)} multi-modality ids carry <2 "
                        f"provenance tags (corroboration/capture-recapture inputs corrupted) e.g. {bad_prov[:3]}")

    # 7. ring ↔ tier consistency
    tiers = {str(r["corpusId"]): r.get("tier") for r in rel_rows}
    ring_err = 0
    for o in obs_rows:
        t, ring = tiers.get(str(o["corpusId"])), o.get("ring")
        if t == "not-relevant" and ring != "out":
            ring_err += 1
        if t is None and ring not in ("unjudged", None):
            ring_err += 1
    if ring_err:
        failures.append(f"[rings] {ring_err} ring/tier inconsistencies")

    # 8. ingestion loss — judged-relevant papers MUST hold a substrate ring (a real gold run
    # silently lost 85 judged-relevant papers incl. 1,500-cite canon; no coverage estimator can
    # see this class, only this check can)
    obs_ring = {str(o["corpusId"]): o.get("ring") for o in obs_rows}
    lost = [c for c, t in tiers.items()
            if t in ("in", "relevant") and obs_ring.get(c) in (None, "out", "unjudged")]
    if lost:
        failures.append(f"[ingestion-loss] {len(lost)} judged-relevant ids have no live ring "
                        f"(never entered the substrate) e.g. {sorted(lost)[:3]}")

    # 9. canon-map attestation — canonicalization maps are DATA: canonical names must be
    # ATTESTED (appear, modulo punctuation/case, among raw keys or candidate titles); invented
    # names (sizes-as-versions) shipped in a real run before this gate existed
    cmap_path = os.path.join(run, "canon-map.json")
    if os.path.exists(cmap_path):
        cmap = json.load(open(cmap_path))
        norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
        vocab = norm(" ".join(list(cmap.keys()) + [r.get("title") or "" for r in cand_rows]))
        ghosts = sorted({v.get("canonical_name") for v in cmap.values()
                         if isinstance(v, dict) and v.get("canonical_name")
                         and norm(v["canonical_name"]) not in vocab})
        if ghosts:
            failures.append(f"[canon-attestation] {len(ghosts)} canonical names attested NOWHERE "
                            f"(invented?) e.g. {ghosts[:4]}")

    # 10. coverage report (informational)
    relevant = [o for o in obs_rows if o.get("relevance_tier") in ("in", "relevant")]
    if obs_rows:
        lab = sum(1 for o in obs_rows if o.get("relevance_tier")) / len(obs_rows)
        warnings.append(f"[report] label-coverage {lab:.2f}")
    if relevant:
        tagged = sum(1 for o in relevant if o.get("primary_family"))
        warnings.append(f"[report] tag-coverage over relevant {tagged}/{len(relevant)}")

    return failures, warnings


if __name__ == "__main__":
    run = sys.argv[1]
    failures, warnings = validate(run)
    for w in warnings:
        print("  ·", w)
    if failures:
        print(f"\n✗ VALIDATION FAILED ({len(failures)}) — fix before ANY downstream step:")
        for f in failures:
            print("  ⚠", f)
        sys.exit(1)
    print("\n✓ all merge/integrity gates pass")
