"""substrate.py — build the run's Observation substrate: ONE record per paper, with RINGS and GATES.

The substrate is the single store every mode reads (coverage / answers / knowledge-building) —
"map once, reuse". It joins acquisition provenance + relevance + aspect tags + scope into
<run>/observations.jsonl, computes the explicit RING division, and emits STAGE-COVERAGE GATES so
quality gaps POP instead of hiding (a mis-tagged batch or an inflated 'Other' bucket must fail a
gate, not silently distort distributions).

Thread-config-driven — NO thread content lives here. Inputs (standard run layout):
  <run>/thread.json                    the thread config the session DERIVED (see SKILL.md contract)
  <run>/candidates.jsonl               {corpusId, title, year, provenance:[modality,...]} from Acquire
  <run>/standardized-relevance.jsonl   from relevance.py
  <run>/tag-batches/<NN>-<name>.jsonl  optional codebook applications, applied IN FILENAME ORDER
                                       (last write wins) — {corpusId, primary_family,
                                       secondary_families, confidence}
  <run>/scope-exclusions.json          optional {"exclusions": {corpusId: reason}} — items excluded
                                       by READING them (system/paper axis the family rule can't see)

Output: <run>/observations.jsonl, records:
   primary_family, secondary_families, tag_batch, tag_confidence, in_scope,
   scope_exclusion_reason, ring, codebook_version}

RINGS (the "inner circle" made first-class — answers DECLARE which ring they run over):
  core      in-scope + judged in/relevant at real depth (single-judge or deeper) — trustworthy center
  candidate in-scope in/relevant but LIGHTLY judged (resolution starts with "light"/"retrieval")
  maybe     judged borderline
  unjudged  no relevance judgment yet (a label gap, NOT a scope verdict)
  out       judged not-relevant, or failed scope on either axis (family OR system/paper)

Usage: python substrate.py <run-dir>
"""
from __future__ import annotations
import glob, json, os, sys
from collections import Counter


def jl(path):
    return [json.loads(l) for l in open(path) if l.strip()] if os.path.exists(path) else []


def build(run):
    cfg = json.load(open(os.path.join(run, "thread.json")))
    scope_cfg = cfg.get("scope", {})
    out_families = set(scope_cfg.get("out_of_scope_families", []))
    codebook_version = cfg.get("codebook_version")

    obs = {}
    for r in jl(os.path.join(run, "candidates.jsonl")):
        c = str(r["corpusId"])
        rec = obs.setdefault(c, {"corpusId": c, "provenance": set()})
        rec.setdefault("title", r.get("title"))
        rec.setdefault("year", r.get("year"))
        rec["provenance"].update(r.get("provenance") or [])

    rel = {str(x["corpusId"]): x for x in jl(os.path.join(run, "standardized-relevance.jsonl"))}

    # tag batches: filename order, last write wins, provenance recorded per record
    for path in sorted(glob.glob(os.path.join(run, "tag-batches", "*.jsonl"))):
        batch = os.path.basename(path).rsplit(".", 1)[0]
        for r in jl(path):
            c = str(r["corpusId"])
            rec = obs.setdefault(c, {"corpusId": c, "provenance": set()})
            rec["primary_family"] = r.get("primary_family")
            rec["secondary_families"] = r.get("secondary_families") or []
            rec["tag_batch"] = batch
            rec["tag_confidence"] = r.get("confidence")

    excl = {}
    p = os.path.join(run, "scope-exclusions.json")
    if os.path.exists(p):
        excl = json.load(open(p)).get("exclusions", {})

    out = []
    for c, r in obs.items():
        sr = rel.get(c, {})
        tier = sr.get("tier")
        fam = r.get("primary_family")
        # in_scope fails on EITHER axis: family (phenomenon) OR read-exclusion (system/paper).
        # When scope.axis == "folded", scope IS the relevance criterion (no separate family test).
        if c in excl:
            in_scope = False
        elif scope_cfg.get("axis") == "separate":
            in_scope = None if not fam else fam not in out_families
        else:
            in_scope = tier in ("in", "relevant", "maybe") if tier else None
        # ring assignment. core-vs-candidate hinges on judgment DEPTH, carried by the resolution
        # name (from the judgments/ filename): resolutions starting with "light" or "retrieval"
        # mean lightly-judged -> candidate; anything deeper (single-judge, panel, adjudicated,
        # audit) -> core. Unjudged is its own ring — NOT "out" (not-yet-judged is a label gap,
        # failing scope is a verdict; conflating them hides the gap).
        res = (sr.get("resolution") or "")
        light = res.startswith("light") or res.startswith("retrieval")
        if tier is None:
            ring = "unjudged"
        elif in_scope is False or tier == "not-relevant":
            ring = "out"
        elif tier in ("in", "relevant"):
            ring = "candidate" if light else "core"
        else:
            ring = "maybe"
        out.append({"corpusId": c, "title": r.get("title"), "year": r.get("year"),
                    "provenance": sorted(r.get("provenance", set())),
                    "relevance_tier": tier, "relevance_resolution": sr.get("resolution"),
                    "primary_family": fam, "secondary_families": r.get("secondary_families", []),
                    "tag_batch": r.get("tag_batch"), "tag_confidence": r.get("tag_confidence"),
                    "in_scope": in_scope, "scope_exclusion_reason": excl.get(c),
                    "ring": ring, "codebook_version": codebook_version})
    with open(os.path.join(run, "observations.jsonl"), "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    return out


def gates(out, has_codebook):
    """STAGE-COVERAGE GATES — refuse to trust distributions when a stage is under-covered.
    Never let a quality drop hide inside a real category ('Other' must be genuine, not untagged)."""
    rel = [o for o in out if o["relevance_tier"] in ("in", "relevant")]
    n = len(rel) or 1
    g = {"n_relevant": len(rel)}
    if has_codebook:
        untagged = sum(1 for o in rel if not o["primary_family"])
        other = sum(1 for o in rel if (o["primary_family"] or "").lower().startswith("other"))
        g["tag_coverage"] = round((n - untagged - other) / n, 3)
        g["untagged"] = untagged
        g["other_bucket"] = other
        g["TAG_GATE"] = "PASS" if g["tag_coverage"] >= 0.90 else \
            "FAIL — do NOT quote family distributions; re-tag the untagged/Other pile first"
    unlabeled = sum(1 for o in out if not o["relevance_tier"])
    g["label_coverage"] = round((len(out) - unlabeled) / (len(out) or 1), 3)
    return g


if __name__ == "__main__":
    run = sys.argv[1]
    out = build(run)
    cfg = json.load(open(os.path.join(run, "thread.json")))
    print(f"observations.jsonl: {len(out)} records")
    print("rings:", dict(Counter(o["ring"] for o in out)))
    print("gates:", json.dumps(gates(out, bool(cfg.get("codebook_version"))), indent=1))
