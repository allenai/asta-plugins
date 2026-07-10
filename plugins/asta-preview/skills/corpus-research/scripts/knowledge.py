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
    from knowledge import load, view, grep
    K = load(run_dir)
    K.lookup(cid)                 # 3-layer membership + how judged + degree
    K.anchor(known_good_ids)      # offline recall vs the store; never_seen -> Acquire
    view(run_dir)                 # materialize <run>/collection.jsonl — the CANONICAL JOIN
                                  # (one row per paper, all stages' fields, id-normalized).
                                  # Query THIS with your ad-hoc joins/jq; rebuild after any
                                  # stage change (stale view = stale answers).
    grep(run_dir, pattern)        # content search over fulltext-cache; LOGS query+hits to
                                  # <run>/queries.log so method notes can cite the query
CLI:  python knowledge.py view <run>   ·   python knowledge.py grep <run> <regex>
"""
from __future__ import annotations
import json, os

RELEVANT_TIERS = ("in", "relevant")


def _jl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


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

    # (find/cites/cited_by were removed 2026-07-09: measured 1 use in ~130 collection queries
    # across 4 runs — ad-hoc joins over the standard files won. See design/forgone-capabilities.)

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


def view(run):
    """Materialize the CANONICAL JOIN: <run>/collection.jsonl — one id-normalized row per paper
    with every stage's fields. This exists because measured runs wrote the same 4-file join
    40+ times each, and every rewrite re-decided id/ring/tier normalization (drift). Query the
    VIEW ad-hoc (python/jq — full freedom); never re-join the raw files.
    Rebuild after any stage change; meta stamps let validate.py catch staleness."""
    obs = {str(r["corpusId"]): r for r in _jl(f"{run}/observations.jsonl")}
    rel = {str(r["corpusId"]): r for r in _jl(f"{run}/standardized-relevance.jsonl")}
    cand = {}
    cpath = f"{run}/candidates.jsonl"
    if os.path.exists(cpath):
        for r in _jl(cpath):
            cand.setdefault(str(r.get("corpusId")), r)
    extr = {}
    import glob as _glob
    for pat in ("extract/merged.jsonl", "extract/records.jsonl", "extract/records/*.jsonl",
                "extractions.jsonl"):
        paths = sorted(_glob.glob(f"{run}/{pat}"))
        for p in paths:
            for r in _jl(p):
                cid = str(r.get("corpusId") or r.get("corpus_id") or "")
                if cid:
                    extr.setdefault(cid, r)
        if paths:
            break
    ids = set(obs) | set(rel)
    rows = []
    for cid in sorted(ids):
        o, j, c = obs.get(cid, {}), rel.get(cid, {}), cand.get(cid, {})
        rows.append({
            "corpusId": cid,
            "title": o.get("title") or c.get("title"),
            "year": o.get("year") or c.get("year"),
            "ring": o.get("ring"),
            "tier": j.get("tier"),
            "criteria": j.get("criteria"),
            "in_scope": o.get("in_scope"),
            "primary_family": o.get("primary_family"),
            "secondary_families": o.get("secondary_families"),
            "provenance": o.get("provenance") or c.get("provenance"),
            "citationCount": c.get("citationCount"),
            "extraction": extr.get(cid),
        })
    out = f"{run}/collection.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    meta = {"rows": len(rows),
            "inputs": {p: int(os.path.getmtime(f"{run}/{p}"))
                       for p in ("observations.jsonl", "standardized-relevance.jsonl")
                       if os.path.exists(f"{run}/{p}")}}
    json.dump(meta, open(f"{run}/collection.meta.json", "w"))
    return out, meta


def grep(run, pattern, flags=0):
    """Content search over <run>/fulltext-cache/*.md. Returns [(corpusId, n_matches)] and
    APPENDS {pattern, hits} to <run>/queries.log — a coverage query is evidence; method notes
    cite it instead of an unrecorded shell grep."""
    import re as _re
    rx = _re.compile(pattern, flags or _re.I)
    hits = []
    cdir = f"{run}/fulltext-cache"
    for fn in sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []:
        if not fn.endswith(".md"):
            continue
        n = len(rx.findall(open(f"{cdir}/{fn}", errors="ignore").read()))
        if n:
            hits.append((fn[:-3], n))
    hits.sort(key=lambda t: -t[1])
    with open(f"{run}/queries.log", "a") as f:
        f.write(json.dumps({"pattern": pattern, "files_hit": len(hits),
                            "hits": hits[:50]}) + "\n")
    return hits



if __name__ == "__main__":
    import sys
    if sys.argv[1] == "view":
        out, meta = view(sys.argv[2])
        print(f"view: {out} ({meta['rows']} rows)")
    elif sys.argv[1] == "grep":
        for cid, n in grep(sys.argv[2], sys.argv[3])[:30]:
            print(f"{cid}\t{n}")
    else:
        K = load(sys.argv[1])
        print(f"knowledge: {len(K.obs)} observations, {len(K.tiers)} labeled, {len(K.edges)} nodes with edges")
        if len(sys.argv) > 2:
            print(json.dumps(K.lookup(sys.argv[2]), indent=1))
