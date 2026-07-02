"""knowledge.py — FIRST-GRADE PRIMITIVE: search/query within the run's OWN accumulated knowledge.

CORPUS-FIRST (principle): the substrate + labeled universe + citation edges ARE the knowledge;
every mode (coverage / answers / knowledge-building) asks the OWN store first. Going to the
network is the cache-miss fallback, never the default. The recall "anchor" (known-good list vs
corpus) is an offline query — the anchor items are usually already in the store, edges and all.

Membership has THREE layers — lookup consults all of them or it lies about what was seen:
  collection (observations)  — curated records
  labeled (relevance tiers)  — EVERYTHING judged, incl. not-relevant (the full universe)
  edges                      — everything whose citation edges were fetched

Run-dir layout contract (produced by substrate.py / relevance.py / the acquisition steps):
  <run>/observations.jsonl            one record per paper (see substrate.py for schema)
  <run>/standardized-relevance.jsonl  {corpusId, tier, ...} for the full labeled universe
  <run>/edges-cache.json              {corpusId: [reference corpusIds]}

Usage:
    from knowledge import load
    K = load(run_dir)
    K.lookup(cid)                 # 3-layer membership + how judged + degree
    K.find(text=, tier=, family=, ring=, year=, provenance=, in_scope=)
    K.cites(cid) / K.cited_by(cid)
    K.anchor(known_good_ids)      # offline recall vs the store; never_seen -> Acquire
"""
from __future__ import annotations
import json, os

RELEVANT_TIERS = ("in", "relevant")


class Knowledge:
    def __init__(self, obs, edges, tiers):
        self.obs = obs            # corpusId(str) -> observation record
        self.edges = edges        # corpusId(str) -> [reference corpusIds]
        self.tiers = tiers        # corpusId(str) -> tier (FULL labeled universe)
        self._citers = {}
        for src, refs in edges.items():
            for r in refs:
                self._citers.setdefault(r, []).append(src)

    def tier(self, cid):
        return self.tiers.get(str(cid))

    def is_relevant(self, cid):
        return self.tier(cid) in RELEVANT_TIERS

    def lookup(self, cid):
        cid = str(cid)
        r = self.obs.get(cid)
        t = self.tiers.get(cid)
        citers = self._citers.get(cid, [])
        return {
            "corpusId": cid,
            "in_knowledge": (t is not None) or (r is not None) or (cid in self.edges),
            "judged": t is not None, "tier": t,
            "in_collection": r is not None,
            "ring": r.get("ring") if r else None,
            "in_scope": r.get("in_scope") if r else None,
            "provenance": r.get("provenance", []) if r else [],
            "primary_family": r.get("primary_family") if r else None,
            "title": r.get("title") if r else None,
            "n_references_stored": len(self.edges.get(cid, [])),
            "cited_by_in_collection": len(citers),
            "cited_by_relevant": sum(1 for s in citers if self.is_relevant(s)),
        }

    def find(self, text=None, tier=None, family=None, ring=None, year=None,
             provenance=None, in_scope=None, limit=None):
        text = text.lower() if text else None
        as_set = lambda v: v if isinstance(v, (list, tuple, set)) else {v}
        out = []
        for r in self.obs.values():
            if text and text not in (r.get("title") or "").lower():
                continue
            if ring is not None and r.get("ring") not in as_set(ring):
                continue
            if tier is not None and r.get("relevance_tier") not in as_set(tier):
                continue
            if family and family != r.get("primary_family") and family not in (r.get("secondary_families") or []):
                continue
            if year is not None and r.get("year") != year:
                continue
            if provenance and provenance not in (r.get("provenance") or []):
                continue
            if in_scope is not None and r.get("in_scope") is not in_scope:
                continue
            out.append(r)
        out.sort(key=lambda r: (r.get("year") or 0), reverse=True)
        return out[:limit] if limit else out

    def cites(self, cid):
        return [self.lookup(r) for r in self.edges.get(str(cid), [])]

    def cited_by(self, cid):
        return [self.lookup(s) for s in self._citers.get(str(cid), [])]

    def anchor(self, ids, label=""):
        """Recall of a KNOWN-GOOD set (survey refs, expert list, enumerated canon) vs the store —
        OFFLINE. Interpret with care: low recall→relevant is often deliberate exclusion, not a
        miss (check n_judged_out_of_scope). Only never_seen are candidate gaps → hand to Acquire."""
        ids = [str(i) for i in ids]
        seen = [i for i in ids if (i in self.tiers or i in self.obs or i in self.edges)]
        relevant = [i for i in seen if self.is_relevant(i)]
        judged_out = [i for i in seen if self.tiers.get(i) in ("not-relevant", "out")]
        never_seen = [i for i in ids if i not in seen]
        n = len(ids) or 1
        return {"label": label, "n": len(ids),
                "recall_relevant": len(relevant) / n, "recall_seen": len(seen) / n,
                "n_relevant": len(relevant), "n_seen": len(seen),
                "n_judged_out_of_scope": len(judged_out),
                "n_never_seen": len(never_seen), "never_seen": never_seen}


def load(run):
    obs = {}
    p = os.path.join(run, "observations.jsonl")
    if os.path.exists(p):
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                obs[str(r["corpusId"])] = r
    tiers = {}
    p = os.path.join(run, "standardized-relevance.jsonl")
    if os.path.exists(p):
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                tiers[str(r["corpusId"])] = r.get("tier")
    edges = {}
    p = os.path.join(run, "edges-cache.json")
    if os.path.exists(p):
        edges = {str(k): [str(x) for x in v] for k, v in json.load(open(p)).items()}
    return Knowledge(obs, edges, tiers)


if __name__ == "__main__":
    import sys
    K = load(sys.argv[1])
    print(f"knowledge: {len(K.obs)} observations, {len(K.tiers)} labeled, {len(K.edges)} nodes with edges")
    if len(sys.argv) > 2:
        print(json.dumps(K.lookup(sys.argv[2]), indent=1))
