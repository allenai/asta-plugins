"""acquire.py — acquisition mechanics: resolve · fetch edges · pool · adapt · MERGE (safely).

The glue layer every acquisition modality needs. Conventions: each modality writes one
`<run>/acq/<modality>.jsonl` (rows: {corpusId, title, year, provenance:[modality], ...extras});
`merge_candidates` then unions ALL acq files into candidates.jsonl. Merge inclusion is
**opt-OUT** (default = every non-raw acq file): a forgotten source can't silently orphan judged
papers — deliberate deferrals are DECLARED in thread.json `acq_deferred`. Always run
`validate.py` after a merge.

Usage (library, from the run dir):
    from s2 import S2; import acquire
    s2 = S2(cache_dir="s2-cache")
    acquire.resolve_titles(titles, s2)                      # parametric seeds -> ids (scored match)
    acquire.fetch_edges(ids, s2, "edges-cache.json")        # checkpointed reference caching
    acquire.pool_references(edges, group_ids, min_count=2)  # survey-ref / co-citation pooling
    acquire.candidates_from_asta("acq/astafind/*.json")     # adapt find/interactive/snowball output
    acquire.write_seeds_file(core_ids, "acq/seeds.json")    # seeds for `snowball --seeds-file`
    acquire.merge_candidates(".")                           # union ALL acq/*.jsonl -> candidates.jsonl
"""
from __future__ import annotations
import glob, json, os, re
from collections import Counter

RAW_MARKERS = ("-all.jsonl", "-raw.jsonl", ".raw.")


# ---------------------------------------------------------------- resolve
def _norm_tokens(t):
    return set(re.sub(r"[^a-z0-9 ]", " ", (t or "").lower()).split())


def resolve_titles(titles, s2, min_score=0.6, fields="title,corpusId,year", limit=5):
    """Resolve free-text titles/names to corpusIds via S2 search with a token-overlap score —
    NEVER take the first hit blindly (name collisions produce silent garbage: a physics paper
    matching a model name). Returns (resolved_rows, unresolved_queries, errored_queries).
    ERRORED ≠ UNRESOLVED: an S2 failure (throttle/outage/missing key) is not evidence the work
    doesn't exist — retry errored queries; only unresolved are true no-confident-match."""
    resolved, unresolved, errored = [], [], []
    for q in titles:
        best, best_score = None, 0.0
        try:
            results = s2.search(q, fields=fields, limit=limit)
        except Exception as e:
            errored.append({"query": q, "error": str(e)[:80]})
            continue
        qt = _norm_tokens(q)
        for r in results:
            ct = _norm_tokens(r.get("title"))
            if not ct:
                continue
            score = len(qt & ct) / (len(qt) or 1)
            if score > best_score:
                best, best_score = r, score
        if best and best_score >= min_score:
            resolved.append({"corpusId": str(best["corpusId"]), "title": best.get("title"),
                             "year": best.get("year"), "seed_query": q,
                             "match_score": round(best_score, 2)})
        else:
            unresolved.append(q)
    return resolved, unresolved, errored


# ---------------------------------------------------------------- edges
def fetch_edges(corpus_ids, s2, cache_path, direction="references", checkpoint_every=10):
    """Fetch citation edges for ids into a persistent {id: [neighbor ids]} cache, checkpointing
    as it goes (a crashed sweep resumes for free). Raw COMPLETE edges — the right substrate for
    graph/coverage signals (ranked expansion is the snowball endpoint's job, not this)."""
    edges = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    todo = [str(c) for c in corpus_ids if str(c) not in edges]
    for i, cid in enumerate(todo):
        try:
            edges[cid] = [str(x) for x in (s2.references(cid) if direction == "references"
                                           else s2.citations(cid))]
        except Exception:
            pass
        if (i + 1) % checkpoint_every == 0:
            json.dump(edges, open(cache_path, "w"))
    json.dump(edges, open(cache_path, "w"))
    return edges


# ---------------------------------------------------------------- pooling
def pool_references(edges, group_ids, min_count=2, exclude=None):
    """Pool what a GROUP collectively cites (survey-ref pooling, seed co-citation): returns
    [(corpusId, count)] for ids cited by ≥ min_count group members, minus exclusions."""
    excl = set(map(str, exclude or [])) | set(map(str, group_ids))
    cnt = Counter()
    for g in map(str, group_ids):
        for r in set(edges.get(g, ())):
            if str(r) not in excl:
                cnt[str(r)] += 1
    return [(c, n) for c, n in cnt.most_common() if n >= min_count]


# ---------------------------------------------------------------- adapters
def candidates_from_asta(paths, provenance="asta-find"):
    """Adapt `asta literature find/interactive/snowball -o out.json` results into candidate rows —
    all three surfaces emit the same envelope ({query, results, thread_id, narrative}) and row
    schema. Keeps everything judge-useful: abstract, snippets, relevanceScore, the paper-finder
    relevance grade, citationCount, venue, url, citation CONTEXTS (snowball/citances — judge-ready
    evidence), and which queries found each paper. `paths` = glob pattern or list of files."""
    files = sorted(glob.glob(paths)) if isinstance(paths, str) else list(paths)
    rows = {}
    for path in files:
        try:
            data = json.load(open(path))
        except Exception:
            continue
        qname = os.path.basename(path).rsplit(".", 1)[0]
        for r in data.get("results", data if isinstance(data, list) else []):
            cid = str(r.get("corpusId") or "")
            if not cid or cid == "None":
                continue
            rj = r.get("relevanceJudgement")
            pf_grade = rj.get("relevance") if isinstance(rj, dict) else None
            rec = rows.setdefault(cid, {"corpusId": cid, "title": r.get("title"),
                                        "year": r.get("year"), "provenance": [provenance],
                                        "abstract": r.get("abstract"), "snippets": r.get("snippets"),
                                        "relevanceScore": r.get("relevanceScore"),
                                        "pf_grade": pf_grade, "citationCount": r.get("citationCount"),
                                        "venue": r.get("venue"), "url": r.get("url"),
                                        "citationContexts": r.get("citationContexts"),
                                        "origins": r.get("origins"),
                                        "found_by_queries": []})
            rec["found_by_queries"].append(qname)
            if (r.get("relevanceScore") or 0) > (rec.get("relevanceScore") or 0):
                rec["relevanceScore"] = r.get("relevanceScore")
            if pf_grade is not None and (rec.get("pf_grade") is None or pf_grade > rec["pf_grade"]):
                rec["pf_grade"] = pf_grade
    return list(rows.values())


candidates_from_asta_find = candidates_from_asta  # back-compat alias


def write_seeds_file(seeds, path):
    """Write a seeds file for `asta literature snowball --seeds-file`. Accepts [corpusId],
    [(corpusId, relevance)], or {corpusId: relevance}; emits the JSON list of
    "corpusId:relevance" strings the CLI parses (relevance 0-3, default 3)."""
    if isinstance(seeds, dict):
        items = list(seeds.items())
    else:
        items = [s if isinstance(s, (list, tuple)) else (s, 3) for s in seeds]
    json.dump([f"{cid}:{rel}" for cid, rel in items], open(path, "w"))
    return len(items)


# ---------------------------------------------------------------- merge
def merge_candidates(run, extra_exclude=()):
    """Union ALL `<run>/acq/*.jsonl` modality files into `<run>/candidates.jsonl` with
    PROVENANCE UNION on overlap (never overwrite — corroboration depends on it). Inclusion is
    opt-OUT: raw files (*-all/*-raw) skipped; deliberate deferrals declared in thread.json
    `acq_deferred`. Run validate.py afterwards — every time."""
    cfgp = os.path.join(run, "thread.json")
    deferred = set(json.load(open(cfgp)).get("acq_deferred", [])) if os.path.exists(cfgp) else set()
    deferred |= set(extra_exclude)
    merged = {}
    for path in sorted(glob.glob(os.path.join(run, "acq", "*.jsonl"))):
        b = os.path.basename(path)
        if any(m in b for m in RAW_MARKERS) or b in deferred:
            continue
        first = next((l for l in open(path) if l.strip()), None)
        if not first or "provenance" not in json.loads(first):
            continue                       # modality files carry provenance; skip other working files
        for line in open(path):
            if not line.strip():
                continue
            r = json.loads(line)
            cid = str(r["corpusId"])
            if cid in merged:
                m = merged[cid]
                m["provenance"] = sorted(set(m.get("provenance") or []) | set(r.get("provenance") or []))
                for k, v in r.items():           # fill gaps, never clobber non-null with null
                    if m.get(k) in (None, [], "") and v not in (None, [], ""):
                        m[k] = v
            else:
                merged[cid] = {**r, "corpusId": cid,
                               "provenance": sorted(set(r.get("provenance") or []))}
    out = os.path.join(run, "candidates.jsonl")
    with open(out, "w") as f:
        for r in merged.values():
            f.write(json.dumps(r) + "\n")
    return len(merged)


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "merge":
        n = merge_candidates(sys.argv[2] if len(sys.argv) > 2 else ".")
        print(f"candidates.jsonl: {n} (now run validate.py)")
    else:
        print(__doc__)
