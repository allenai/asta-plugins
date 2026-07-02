"""coverage_signals.py — the coverage-signal suite: estimate/localize what the corpus is MISSING.

Coverage is never a single scalar. Signals play four roles — ESTIMATORS of the missing count,
CONVERGENCE modulators, RECALL anchors, and LOCALIZERS of where gaps live — and are combined by
reliability-weighted triangulation into a verdict (see references/coverage-playbook.md). Every
signal carries a self-check (label-coverage, overlap-gate, assumption flag); discard signals that
fail their check rather than averaging them in.

All functions are argument-driven (edges dicts, id lists, relevance maps) — no run-layout
assumptions except `report(run_dir)`, which reads the standard layout via knowledge.load.
"""
from __future__ import annotations
import json, math, os, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knowledge as _K


# ---------------------------------------------------------------- estimators
def chapman(n1, n2, m):
    """Bias-corrected two-sample capture-recapture (Chapman). m = overlap."""
    N = (n1 + 1) * (n2 + 1) / (m + 1) - 1
    var = (n1 + 1) * (n2 + 1) * (n1 - m) * (n2 - m) / (((m + 1) ** 2) * (m + 2)) if m >= 0 else 0
    return {"N_hat": round(N), "ci95": round(1.96 * math.sqrt(var)) if var > 0 else 0}


def capture_recapture_modalities(sample_a_ids, sample_b_ids, in_scope_ids):
    """Population estimate from two INDEPENDENT acquisition modalities (e.g. seed-driven vs
    survey/gap-driven), restricted to curated in-scope items. HETEROGENEOUS catchability (famous
    items over-captured) inflates apparent overlap ⇒ treat N_hat as a LOWER bound. The companion
    honesty metric: the fraction found by ONLY ONE modality — high single-modality share means the
    population is under-sampled and a single-modality 'comprehensive' claim would badly undercount."""
    S = set(map(str, in_scope_ids))
    A, B = set(map(str, sample_a_ids)) & S, set(map(str, sample_b_ids)) & S
    m = len(A & B)
    est = chapman(len(A), len(B), m)
    return {**est, "n_a": len(A), "n_b": len(B), "overlap": m,
            "only_one_modality": len((A | B) - (A & B)),
            "captured": len(A | B), "est_missing": max(0, est["N_hat"] - len(A | B)),
            "note": "lower bound (heterogeneous catchability)"}


def unseen_class_incidence(edges, relevance_bool, collection_ids):
    """PREFERRED backward-axis estimate: many-occasion Chao1 over REAL citation incidence.
    Each collection paper = an occasion; frequency spectrum of relevant external refs -> Chao1.
    GATE: label_coverage < 1 makes this a lower bound (judge every capture for a clean number).
    edges: {paper: [referenced ids]}; relevance_bool: {id: bool} over labeled refs."""
    S = set(map(str, collection_ids))
    inc = Counter()
    for c in S:
        for r in set(edges.get(c, ())):
            if str(r) not in S:
                inc[str(r)] += 1
    labeled = [r for r in inc if r in relevance_bool]
    rel = {r: inc[r] for r in labeled if relevance_bool[r]}
    spec = Counter(rel.values())
    f1, f2, s_obs = spec.get(1, 0), spec.get(2, 0), len(rel)
    f0 = f1 * (f1 - 1) / (2 * (f2 + 1))
    return {"occasions": len(S), "external_refs": len(inc),
            "label_coverage": round(len(labeled) / len(inc), 2) if inc else None,
            "relevant_observed": s_obs, "f1": f1, "f2": f2,
            "chao1_est": round(s_obs + f0), "missed_est": round(f0),
            "good_turing_missing_mass": round(f1 / sum(rel.values()), 2) if rel else None,
            "note": "many-occasion Chao1 on real edges; LOWER bound while label_coverage<1"}


# ------------------------------------------------------- stratifier / anchors
def reference_pool_recall(edges, core_ids, tiers, thresholds=(15, 10, 7, 5, 3)):
    """STRATIFY the flat missing-estimate into canonical vs long-tail (never quote a flat '% missing').
    Pool what the CORE collectively cites (offline analogue of reading every core paper's
    Related-Work at once); recall at each citation-frequency threshold. Healthy mature corpus:
    ~100% recall at >=3; the misses live in the singly-cited periphery. High-frequency never-seen
    items = concrete, community-sourced gap candidates (cross-check with missed-centrality)."""
    core = [c for c in map(str, core_ids) if c in edges]
    known = set(tiers)
    refcount = Counter()
    for c in core:
        for ref in set(edges[c]):
            refcount[str(ref)] += 1
    strata = {}
    for t in thresholds:
        pop = [r for r, n in refcount.items() if n >= t]
        seen = [r for r in pop if r in known]
        strata[f">={t}"] = {"n": len(pop), "in_knowledge": len(seen),
                            "recall": round(len(seen) / len(pop), 3) if pop else None,
                            "never_seen": len(pop) - len(seen)}
    gaps = [(r, n) for r, n in refcount.most_common() if r not in known]
    return {"core_with_edges": len(core), "distinct_cited": len(refcount),
            "recall_by_citation_frequency": strata, "top_never_seen_gaps": gaps[:20]}


# ---------------------------------------------------------------- localizers
def eigenvector_centrality(edges, seed_ids, relevance, weight="binary", iters=300, tol=1e-6):
    """THE validated relevance PRIOR (paper-finder CentralityAgent lineage): eigenvector centrality
    with each edge weighted by the CITING paper's relevance. Validated top-decile ~80% relevant vs
    ~32% unweighted. KEEP THE WEIGHT SIMPLE — binary('citer relevant') ~= linear; complexity adds
    nothing. Use to prioritize labeling/acquisition and rank gap candidates. Pure-python power
    iteration; feed the persisted edge cache, never refetch."""
    S = set(map(str, seed_ids))
    def relnum(c):
        if c in S:
            return 3
        return {"in": 3, "relevant": 2, "maybe": 1, "out": 0, "not-relevant": 0}.get(relevance.get(c), 0)
    wf = (weight if callable(weight)
          else (lambda s: 1.0 if relnum(s) >= 2 else 0.0) if weight == "binary"
          else (lambda s: float(relnum(s))))
    nodeset = set(edges) | S
    adj = {}
    for s, ds in edges.items():
        w = wf(s)
        if w <= 0:
            continue
        for d in ds:
            if d in nodeset and d != s:
                adj.setdefault(s, []).append((d, w))
                adj.setdefault(d, []).append((s, w))
    x = {n: 1.0 for n in nodeset}
    for _ in range(iters):
        nxt = {n: 0.0 for n in nodeset}
        for n in nodeset:
            xn = x[n]
            for m, w in adj.get(n, ()):
                nxt[m] += w * xn
        nrm = sum(v * v for v in nxt.values()) ** 0.5 or 1.0
        nxt = {n: v / nrm for n, v in nxt.items()}
        if sum(abs(nxt[n] - x[n]) for n in nodeset) < tol:
            return nxt
        x = nxt
    return x


def citation_graph(edges, collection_ids, top_missed=15):
    """Structure signals over the cached graph: self-containment (internal/external ref ratio) and
    MISSED-HIGH-CENTRALITY (uncaptured nodes many collection papers cite — triage: in-scope canon
    vs out-of-scope hub; famous foundational hubs are usually NOT in-scope gaps)."""
    S = set(map(str, collection_ids))
    internal = external = 0
    ext_count = Counter()
    for c in S:
        for r in edges.get(c, ()):
            if r in S:
                internal += 1
            else:
                external += 1
                ext_count[r] += 1
    return {"self_containment": round(internal / (internal + external), 3) if internal + external else None,
            "missed_high_centrality": ext_count.most_common(top_missed)}


# -------------------------------------------------------------- distributions
def content_distribution(observations, key="primary_family", ring=("core", "candidate")):
    """Family/tag distribution over the answer set — ONLY trustworthy if the tag-coverage gate
    passes (see substrate.py); an inflated 'Other/untagged' bucket silently distorts this."""
    rows = [o for o in observations if o.get("ring") in ring]
    return dict(Counter(o.get(key) for o in rows).most_common())


def temporal(observations, ring=("core", "candidate")):
    yrs = sorted(o["year"] for o in observations if o.get("year") and o.get("ring") in ring)
    return {"span": (yrs[0], yrs[-1]) if yrs else None,
            "median": yrs[len(yrs) // 2] if yrs else None}


# ------------------------------------------------------------------- verdict
def report(run):
    """Offline coverage report over the standard run layout. Deliberately minimal — the [J]
    reasoning-over-coverage (triangulate, interpret, decide) is the agent's job per the playbook;
    this computes the [T] signal values."""
    K = _K.load(run)
    core = [c for c, o in K.obs.items() if o.get("ring") == "core"]
    relevance_bool = {c: (t in ("in", "relevant")) for c, t in K.tiers.items()}
    obs = list(K.obs.values())
    R = {"n_core": len(core), "n_labeled": len(K.tiers),
         "content": content_distribution(obs),
         "temporal": temporal(obs),
         "unseen_class": unseen_class_incidence(K.edges, relevance_bool, core),
         "reference_pool": reference_pool_recall(K.edges, core, K.tiers),
         "citation_graph": citation_graph(K.edges, core)}
    cent = eigenvector_centrality(K.edges, core, K.tiers)
    ranked = sorted(((c, v) for c, v in cent.items() if c not in set(core)), key=lambda x: -x[1])
    top = ranked[:max(1, len(ranked) // 10)]
    R["centrality_prior"] = {
        "n_ranked": len(ranked),
        "top_decile_relevant_rate": round(sum(1 for c, _ in top if relevance_bool.get(c)) / len(top), 2) if top else None}
    return R


if __name__ == "__main__":
    import pprint
    pprint.pp(report(sys.argv[1]))
