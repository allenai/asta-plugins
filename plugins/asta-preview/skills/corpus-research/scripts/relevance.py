"""relevance.py — normalize scattered relevance judgments into ONE standardized record per paper.

Relevance is the COMMON CURRENCY across the whole run (retrieval scores, judge verdicts, panel
adjudications, audits all speak it). Every judgment source is normalized to:

    {corpusId, tier, criteria: [{criterion, grade}], resolution, judged_by}

  tier       in | relevant | maybe | not-relevant   (graded, not boolean)
  criteria   per-criterion 0-3 grades against the THREAD's criteria (from thread.json) — generic
             list, NEVER hardcoded criterion names
  resolution how the tier was determined — later judgment files override earlier ones, so order
             the inputs least→most authoritative (e.g. retrieval-judged < single-judge <
             panel-adjudicated < audit)

Inputs: <run>/judgments/<NN>-<resolution>.jsonl, applied IN FILENAME ORDER (last wins).
  Each line: {corpusId, tier|verdict, criteria?, judged_by?}
Output: <run>/standardized-relevance.jsonl

Usage: python relevance.py <run-dir>
"""
from __future__ import annotations
import glob, json, os, sys
from collections import Counter

TIER_ALIASES = {"in": "in", "relevant": "relevant", "maybe": "maybe", "borderline": "maybe",
                "out": "not-relevant", "not-relevant": "not-relevant", "no": "not-relevant",
                "yes": "relevant", "true": "relevant", "false": "not-relevant"}


def normalize(run):
    out = {}
    for path in sorted(glob.glob(os.path.join(run, "judgments", "*.jsonl"))):
        resolution = os.path.basename(path).rsplit(".", 1)[0].split("-", 1)[-1]
        for line in open(path):
            if not line.strip():
                continue
            r = json.loads(line)
            c = str(r["corpusId"])
            raw = str(r.get("tier") or r.get("verdict") or "").lower()
            tier = TIER_ALIASES.get(raw)
            if tier is None:
                continue
            crit = r.get("criteria") or []
            if isinstance(crit, dict):                       # {criterion: grade} -> list form
                crit = [{"criterion": k, "grade": v} for k, v in crit.items()]
            out[c] = {"corpusId": c, "tier": tier, "criteria": crit,
                      "resolution": resolution, "judged_by": r.get("judged_by")}
    with open(os.path.join(run, "standardized-relevance.jsonl"), "w") as f:
        for r in out.values():
            f.write(json.dumps(r) + "\n")
    return out


if __name__ == "__main__":
    run = sys.argv[1]
    out = normalize(run)
    print(f"standardized-relevance.jsonl: {len(out)} papers")
    print("tiers:", dict(Counter(r["tier"] for r in out.values())))
    print("resolutions:", dict(Counter(r["resolution"] for r in out.values())))
