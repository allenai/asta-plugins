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
import glob, json, math, os, re, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knowledge as _K


# ---------------------------------------------------------------- estimators
def chapman(n1, n2, m):
    """Bias-corrected two-sample capture-recapture (Chapman). m = overlap."""
    N = (n1 + 1) * (n2 + 1) / (m + 1) - 1
    var = (n1 + 1) * (n2 + 1) * (n1 - m) * (n2 - m) / (((m + 1) ** 2) * (m + 2)) if m >= 0 else 0
    return {"N_hat": round(N), "ci95": round(1.96 * math.sqrt(var)) if var > 0 else 0}


def capture_recapture_modalities(sample_a_ids, sample_b_ids, in_scope_ids, overlap_gate=0.10):
    """Population estimate from two INDEPENDENT acquisition modalities (e.g. seed-driven vs
    survey/gap-driven), restricted to curated in-scope items. SELF-CHECK (do not skip): CR is
    only valid when the two samples genuinely CO-CAPTURE from the same population — modalities
    with disjoint catchments (different eras/communities) produce a tiny overlap and an absurdly
    inflated N_hat. `reliable=False` when overlap/captured < overlap_gate ⇒ DISCARD the estimate
    (report it as gated, don't average it in). Also: heterogeneous catchability (famous items
    over-captured) makes even a reliable N_hat a LOWER bound. The companion honesty metric:
    only_one_modality — a high single-modality share means the population is under-sampled."""
    S = set(map(str, in_scope_ids))
    A, B = set(map(str, sample_a_ids)) & S, set(map(str, sample_b_ids)) & S
    m = len(A & B)
    est = chapman(len(A), len(B), m)
    captured = len(A | B)
    overlap_frac = m / captured if captured else 0.0
    return {**est, "n_a": len(A), "n_b": len(B), "overlap": m,
            "overlap_frac": round(overlap_frac, 3),
            "reliable": overlap_frac >= overlap_gate,
            "only_one_modality": captured - m,
            "captured": captured, "est_missing": max(0, est["N_hat"] - captured),
            "note": "lower bound (heterogeneous catchability); DISCARD if reliable=False"}


def yield_by_frequency(rows, freq_key, is_relevant, cap=5):
    """Relevance yield as a function of capture frequency (e.g. how many hubs cite a forward-
    citation candidate). Purpose: ground a DEFERRED-SLICE residual estimate — when you judge the
    high-frequency slice and defer the low-frequency tail, extrapolate the tail's expected
    relevant count from the yield GRADIENT of the judged strata (yield falls monotonically with
    frequency), instead of a gut-feel discount. rows: candidate dicts; freq_key: the frequency
    field; is_relevant: fn(corpusId)->bool|None (None = unjudged, skipped)."""
    from collections import defaultdict
    byf = defaultdict(lambda: [0, 0])
    for r in rows:
        v = is_relevant(str(r["corpusId"]))
        if v is None:
            continue
        f = min(int(r.get(freq_key) or 0), cap)
        byf[f][0] += bool(v)
        byf[f][1] += 1
    return {f: {"relevant": a, "judged": n, "yield": round(a / n, 3) if n else None}
            for f, (a, n) in sorted(byf.items())}


def strategy_decay(yields, min_points=8):
    """[T] Fit a saturating exponential f(n)=A*(1-exp(-n/tau)) to ONE strategy's cumulative
    new-relevant curve to estimate how exhausted THAT strategy is — NEVER population coverage.
    RECEIPT: on a real 25-query sweep the fit was UNIDENTIFIABLE at 10 and 15 steps (curve still
    ~linear, best A rode the grid ceiling) and only firmed up by 25 steps, where A measured
    strategy exhaustion (~394, progress ~63%) NOT the population (708+ known relevant) — so the
    asymptote is a per-strategy ceiling, not a denominator. yields: per-step NEW-relevant counts
    in acquisition order. Grid A in [cum, 6*cum]; closed-form tau per A via regression-through-
    origin on the linearized curve ln(1-cum/A) = -(1/tau)*n; pick A by least squares over ALL
    steps. identifiable=False when the curve is still ~linear (best A > 3*cum, riding the ceiling)
    — then A is a lower bound and progress an upper bound, not committed numbers."""
    ys = [max(0, int(y)) for y in yields]
    n = len(ys)
    cum, s = [], 0
    for y in ys:
        s += y
        cum.append(s)
    total = cum[-1] if cum else 0
    label = "STRATEGY-RELATIVE exhaustion — never population coverage"
    base = {"A": None, "tau": None, "progress": None, "cum": total, "n_points": n, "label": label}
    if n < min_points:
        return {**base, "identifiable": False, "note": f"{n} points (< min_points {min_points})"}
    if total <= 0:
        return {**base, "identifiable": False, "note": "no relevant yield to fit"}
    xs = list(range(1, n + 1))
    sxx = sum(x * x for x in xs)
    lo, hi, steps = float(total), 6.0 * total, 600
    best = None
    for i in range(steps + 1):
        A = lo + (hi - lo) * i / steps
        L, ok = [], True
        for c in cum:
            r = 1.0 - c / A
            if r <= 0:  # A must exceed every cumulative point for the log to exist
                ok = False
                break
            L.append(math.log(r))
        if not ok:
            continue
        slope = sum(x * l for x, l in zip(xs, L)) / sxx  # regression through origin
        if slope >= 0:  # non-decaying — no exhaustion signal
            continue
        tau = -1.0 / slope
        sse = sum((A * (1.0 - math.exp(-x / tau)) - c) ** 2 for x, c in zip(xs, cum))
        if best is None or sse < best[0]:
            best = (sse, A, tau)
    if best is None:
        return {**base, "identifiable": False, "note": "no admissible fit (curve too flat/linear)"}
    _, A, tau = best
    identifiable = A <= 3.0 * total
    return {**base, "A": round(A, 1), "tau": round(tau, 2),
            "progress": round(total / A, 3), "identifiable": identifiable,
            "note": ("fit firm — asymptote = this strategy's ceiling (not the population)"
                     if identifiable else
                     "curve still ~linear; A is a LOWER bound, progress an UPPER bound")}


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
    uc = unseen_class_incidence(K.edges, relevance_bool, core)
    R = {"n_core": len(core), "n_labeled": len(K.tiers),
         "content": content_distribution(obs),
         "temporal": temporal(obs),
         "unseen_class": uc,
         "reference_pool": reference_pool_recall(K.edges, core, K.tiers),
         "citation_graph": citation_graph(K.edges, core)}
    cent = eigenvector_centrality(K.edges, core, K.tiers)
    ranked = sorted(((c, v) for c, v in cent.items() if c not in set(core)), key=lambda x: -x[1])
    top = ranked[:max(1, len(ranked) // 10)]
    R["centrality_prior"] = {
        "n_ranked": len(ranked),
        "top_decile_relevant_rate": round(sum(1 for c, _ in top if relevance_bool.get(c)) / len(top), 2) if top else None}
    # TRIANGULATION TRANSPARENCY: the verdict must SAY which estimators were used vs gated-out
    # and why — a silently skipped estimator is indistinguishable from a forgotten one.
    lc = uc.get("label_coverage") or 0
    R["estimators"] = {
        "reference_pool_recall": "USED (stratify canonical vs tail; recompute AFTER the last "
                                 "gap-closure round — stale strata misreport recall)",
        "chao1_incidence": ("USED" if lc >= 0.5 else
                            f"GATED: label_coverage={lc} over external refs (<0.5) — judge more "
                            f"captures (relevance-as-you-go) or report as unavailable"),
        "capture_recapture_modalities": "run separately with TRUE modality sets (from acq/ files, "
                                        "not candidates provenance); DISCARD if reliable=False "
                                        "(disjoint catchments)",
        "deferred_slice_residual": "if any slice was deferred, estimate its residual via "
                                   "yield_by_frequency gradient extrapolation — never gut-feel",
    }
    return R


# --------------------------------------------------------------- verdict gate
# DEFAULT-PROMISE checks for a coverage VERDICT (playbook Expectations preamble). Patterns are
# deliberately GENEROUS (many phrasings) — this gates PRESENCE of each promised element, not its
# wording. Each entry: (label, compiled pattern, whether a number must co-occur on the same line).
_VERDICT_CHECKS = {
    "regime": (r"regime|enumerab|countable|closed[- ]?ish|open[- ]?ended|open[- ]?denominator|"
               r"no fraction (?:is )?definable|sampled,?\s+not enumerated|"
               r"parts (?:we|you) can count|denominator", False),
    "external_anchor": (r"held[- ]?out|community list|registr(?:y|ies)|persona|web[- ]?librarian|"
                        r"external[- ]?(?:enumeration )?anchor|enumeration anchor|leaderboard|"
                        r"awesome list|wikipedia list|completeness critic|adversarial critic|"
                        r"held[- ]?out canon|\bcanon\b", True),
    "gap_map": (r"\bgaps?\b|\bthin\b|periphery|peripheral|under[- ]?stud|under[- ]?sampl|"
                r"ranked gap|localiz|field[- ]?thin|corpus[- ]?thin", False),
    "as_of": (r"as[- ]of\b|as of \d", False),
    "refresh": (r"refresh", False),
}
_LOSS_TERMS = {
    "filter-false-negative": r"filter[- ]?(?:false[- ]?neg\w*|fn\b|false neg)",
    "truncation": r"truncat",
    "unjudged/deferred": r"un-?judged|deferred|not (?:yet )?judged|dropped[- ]?unjudged|acq_deferred",
}


def _resolve_verdict(path):
    """Accept a file, or a dir/run root — find the verdict by the standard names."""
    if os.path.isfile(path):
        return path
    for cand in ("coverage-verdict.md", "coverage/VERDICT.md", "VERDICT.md",
                 "coverage/coverage-verdict.md"):
        p = os.path.join(path, cand)
        if os.path.isfile(p):
            return p
    return None


def _sibling_evidence(pattern, run_dir, verdict_file):
    """Diagnostic only: if the verdict misses an item, does a sibling coverage/*.md carry it?
    (The doctrine wants it IN the verdict — this just points the author at where it lives.)"""
    if not run_dir:
        return None
    hits = []
    for p in glob.glob(f"{run_dir}/**/*.md", recursive=True):
        if os.path.abspath(p) == os.path.abspath(verdict_file):
            continue
        try:
            if re.search(pattern, open(p, errors="ignore").read(), re.I):
                hits.append(os.path.basename(p))
        except Exception:
            continue
    return hits[:3] or None


def verdict_gate(verdict_path, run_dir=None):
    """[T] produce-X-gate-X for a coverage VERDICT file — the verdict now gets the same treatment
    report_gate.py gives the report. RECEIPT: verdict-time doctrine measurably decays when carried
    in prose, so the DEFAULT-PROMISE items (playbook Expectations preamble) must be PRESENT in the
    verdict itself. Checks: (1) denominator-REGIME language (closed/enumerable vs open-ended, or
    'no fraction definable'); (2) an EXTERNAL ANCHOR named with a number (community list / registry
    / held-out canon / persona / enumeration anchor); (3) a GAP MAP (thin/gap language, ideally
    with named families/strata); (4) AS-OF date + REFRESH trigger; (5) at least one named LOSS term
    (filter false-negative / truncation / unjudged-deferred). Patterns are generous — gates
    presence, not wording; a miss on a real verdict is a FINDING. Returns (fails, notes). run_dir
    (optional): when an item is missing, notes whether a sibling coverage/*.md carries the evidence
    (diagnostic — the gate still fails; doctrine wants it in the verdict)."""
    vf = _resolve_verdict(verdict_path)
    if not vf:
        return [f"no verdict file found at {verdict_path}"], []
    text = open(vf, errors="ignore").read()
    lines = text.splitlines()
    fails, notes = [], [f"verdict: {vf}"]

    for name, (pat, needs_num) in _VERDICT_CHECKS.items():
        if needs_num:
            present = any(re.search(pat, ln, re.I) and re.search(r"\d", ln) for ln in lines)
        else:
            present = bool(re.search(pat, text, re.I))
        if present:
            notes.append(f"{name}: present")
        else:
            msg = {"regime": "no denominator-regime language (closed/enumerable vs open-ended)",
                   "external_anchor": "no external anchor named WITH a number (community list / "
                                      "registry / held-out canon / persona)",
                   "gap_map": "no gap map (thin/gap language with named families/strata)",
                   "as_of": "no as-of date", "refresh": "no refresh trigger"}[name]
            sib = _sibling_evidence(pat, run_dir, vf)
            if sib:
                msg += f" [but present in sibling(s): {sib} — put it IN the verdict]"
            fails.append(msg)

    found_loss = [k for k, pat in _LOSS_TERMS.items() if re.search(pat, text, re.I)]
    missing_loss = [k for k in _LOSS_TERMS if k not in found_loss]
    notes.append(f"loss terms named: {found_loss or 'NONE'}"
                 + (f" (missing: {missing_loss})" if found_loss and missing_loss else ""))
    if not found_loss:
        msg = "no named loss terms (filter false-negative / truncation / unjudged-deferred)"
        sib = _sibling_evidence("|".join(_LOSS_TERMS.values()), run_dir, vf)
        if sib:
            msg += f" [but present in sibling(s): {sib} — put it IN the verdict]"
        fails.append(msg)

    # gap-map depth diagnostic (does not fail the gate): named families/strata alongside gaps
    if re.search(r"famil(?:y|ies)|strat(?:um|a)|\bhead\b|\btail\b", text, re.I):
        notes.append("gap_map: named families/strata detected (good)")

    return fails, notes


if __name__ == "__main__":
    import pprint
    argv = sys.argv[1:]
    cmd = argv[0] if argv else ""
    if cmd == "verdict-gate":
        run = argv[argv.index("--run") + 1] if "--run" in argv else None
        fails, notes = verdict_gate(argv[1], run)
        for n in notes:
            print("  ·", n)
        if fails:
            print("VERDICT GATE: FAIL")
            for f in fails:
                print("  ✗", f)
            sys.exit(1)
        print("VERDICT GATE: PASS")
    elif cmd == "strategy-decay":
        data = json.load(open(argv[1]))
        ys = [d["new_gold"] if isinstance(d, dict) else int(d) for d in data]
        pprint.pp(strategy_decay(ys))
    else:
        pprint.pp(report(argv[0]))
