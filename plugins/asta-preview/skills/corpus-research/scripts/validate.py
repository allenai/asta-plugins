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
 11. FLEET-OUTPUT salt gate (merge-time; primitive-work ruling 1 — the trust boundary
     moved OUT of shards.py, which sessions re-derive, to the output boundary where it
     fires no matter how sharding was done): judgments present ⇒ salts.json present with
     real salts that were actually judged, OR an allow-unsalted reason recorded
     (salts.json "_unsalted_declared" / thread.json "allow_unsalted").
 12. UNJUDGED ≠ semantic bucket (a2-run6 F2: ring papers with no judgment row fell into
     "other-*" — pipeline state absorbed into a verdict): unjudged rows must never sit in
     a catch-all family bucket; "other" only ever means judged-but-matched-no-family.
 13. EXTRACTION IDEMPOTENCY (report, extraction hygiene; receipt: a run double-extracted papers):
     the same corpusId in MULTIPLE extraction batches double-counts at aggregation —
     loud warning listing the ids and the batches carrying them.
 14. IDENTICAL-UNLESS AT FILE GRAIN (report, extraction hygiene; receipt: 20/20 boilerplate):
     >80% identical `unless` strings in one extraction/audit file = a file-wide caveat
     masquerading as per-row reasoning — warning suggesting a file-grain scope note.

Derived-artifact gate (a2-run6 audit; run it on ANY table derived over the ring):
  python validate.py derived <run-dir> <table.jsonl> [--key corpusId] [--bucket <field>]
                                                     [--budget 0.10]
  (a) JOIN COMPLETENESS — every live-ring member matched a row (missing → loud FAIL list);
  (b) CATCH-ALL BUDGET — empty/"other" bucket over threshold → STOP with the bucket dumped;
  (c) PROVENANCE — sidecar <table>.meta.json {"inputs": {path: n_rows}} listing inputs
      ACTUALLY CONSUMED, re-counted now (an under-reading glob is visible);
  plus UNJUDGED ≠ bucket inside the table (unjudged ids carrying a semantic value FAIL).

Usage: python validate.py <run-dir>          (exit 0 = all gates pass)
"""
from __future__ import annotations
import glob, json, os, re, sys
from collections import Counter

RAW_MARKERS = ("-all.jsonl", "-raw.jsonl", ".raw.")
# catch-all bucket values (empty counts too): only ever legal for JUDGED rows that matched
# no family — never for pipeline gaps ("never hide a quality drop in a catch-all bucket")
CATCHALL = re.compile(r"^(others?\b|misc\b|catch[- ]?all|uncategori[sz]ed|unknown\b)", re.I)
LIVE_RING_EXCLUDED = (None, "", "out", "unjudged")


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

    # 11. fleet-output salt gate — fires at MERGE regardless of how shards were built
    # (round-13 headless re-implemented sharding and the in-convenience gate never fired)
    if judged:
        sp = os.path.join(run, "judge-input", "salts.json")
        salts = json.load(open(sp)) if os.path.exists(sp) else None
        declared = (salts or {}).get("_unsalted_declared") or cfg.get("allow_unsalted")
        planted = {c for m in (salts or {}).values() if isinstance(m, dict) for c in m}
        if planted:
            missing = planted - judged
            if missing == planted:
                failures.append(f"[fleet-salt] NONE of the {len(planted)} planted salt ids "
                                f"appear in judgments — shards were rebuilt/judged without "
                                f"their salts (per-judge calibration lost)")
            elif missing:
                warnings.append(f"[fleet-salt] {len(missing)}/{len(planted)} salt ids never "
                                f"judged e.g. {sorted(missing)[:3]}")
        elif declared:
            warnings.append(f"[fleet-salt] unsalted fleet DECLARED: {declared}")
        else:
            failures.append("[fleet-salt] judgments present but no salts and no recorded "
                            "reason — a fleet without planted calibration items is "
                            "uncalibratable; re-shard with salts or declare "
                            "allow_unsalted='<reason>' (salts.json or thread.json)")

    # 12. UNJUDGED ≠ semantic bucket — pipeline state must stay loud, never absorbed
    unj_catch = [str(o["corpusId"]) for o in obs_rows
                 if tiers.get(str(o["corpusId"])) is None
                 and CATCHALL.match(str(o.get("primary_family") or ""))]
    if unj_catch:
        failures.append(f"[unjudged-bucket] {len(unj_catch)} UNJUDGED rows sit in a "
                        f"catch-all semantic bucket (missing-data absorbed into a verdict) "
                        f"e.g. {unj_catch[:3]}")

    # 13. + 14. extraction batches (both TOLERANT readers — extraction schemas vary by
    # round; bad lines are skipped, absent extract/ dirs skip both checks entirely, so
    # LEGACY runs without these structures pass untouched)
    exfiles = [p for p in ([os.path.join(run, "extractions.jsonl")]
                           + sorted(glob.glob(os.path.join(run, "extract", "**", "*.jsonl"),
                                              recursive=True)))
               if os.path.isfile(p)
               and not os.path.basename(p).startswith(("merged", "digest"))]

    def _jl_tolerant(p):
        rows = []
        for l in open(p, errors="replace"):
            if not l.strip():
                continue
            try:
                r = json.loads(l)
            except Exception:
                continue
            if isinstance(r, dict):
                rows.append(r)
        return rows

    # 13. extraction idempotency — same corpusId in >=2 batches inflates every aggregate
    seen_in = {}
    for p in exfiles:
        rel = os.path.relpath(p, run)
        for r in _jl_tolerant(p):
            cid = r.get("corpusId", r.get("corpus_id", r.get("paperId")))
            if cid is not None:
                seen_in.setdefault(str(cid), set()).add(rel)
    multi = {c: fs for c, fs in seen_in.items() if len(fs) >= 2}
    if multi:
        ex = "; ".join(f"{c} ({', '.join(sorted(fs))})"
                       for c, fs in sorted(multi.items())[:5])
        warnings.append(f"[extract-dup] {len(multi)} corpusIds appear in >=2 extraction "
                        f"batches — double-extraction inflates aggregates; dedupe by "
                        f"corpusId at aggregation (ids: "
                        f"{sorted(multi)[:10]}{'…' if len(multi) > 10 else ''}) e.g. {ex}")

    # 14. identical-unless at file grain — a caveat copied onto >80% of a file's rows is a
    # FILE property, not row reasoning; move it to a file-grain scope note
    for p in exfiles + sorted(glob.glob(os.path.join(run, "*audit*.jsonl"))):
        vals = []

        def _collect(x):
            if isinstance(x, dict):
                u = x.get("unless")
                if isinstance(u, str) and u.strip():
                    vals.append(re.sub(r"\s+", " ", u.strip().lower()))
                for v in x.values():
                    _collect(v)
            elif isinstance(x, list):
                for v in x:
                    _collect(v)
        for r in _jl_tolerant(p):
            _collect(r)
        if len(vals) >= 10:
            top, n = Counter(vals).most_common(1)[0]
            if n / len(vals) > 0.80:
                warnings.append(f"[unless-boilerplate] {os.path.relpath(p, run)}: "
                                f"{n}/{len(vals)} unless strings identical ({top[:80]!r}) "
                                f"— a file-wide caveat belongs in a file-grain scope note, "
                                f"not copied per row (per-row unless is specific-and-"
                                f"checkable or it is boilerplate)")

    return failures, warnings


def validate_derived(run, table, key="corpusId", bucket=None, budget=0.10):
    """Derived-artifact GATE at the output boundary (a2-run6 F1-F3: the extraction/tagging
    stage had no gate, so a session-authored deriver silently mis-bucketed ring papers).
    Constrains WHAT, not HOW — any table derived over the ring must pass:
      (a) join completeness over the live ring (missing rows → loud FAIL with the list);
      (b) catch-all budget (empty/"other"/misc over threshold → STOP, bucket dumped);
      (c) a provenance sidecar listing inputs ACTUALLY CONSUMED, re-counted against disk;
      (d) UNJUDGED ≠ bucket: rows for unjudged ids must not carry a semantic value."""
    failures, warnings = [], []
    rows = jl(table)
    if not rows:
        return [f"[derived] {table}: missing or empty — nothing to gate"], warnings
    tids = {str(r.get(key)) for r in rows if r.get(key) is not None}
    obs_rows = jl(os.path.join(run, "observations.jsonl"))
    tiers = {str(r["corpusId"]): r.get("tier")
             for r in jl(os.path.join(run, "standardized-relevance.jsonl"))}
    # (a) join completeness — every live-ring member matched a source row
    ring_ids = {str(o["corpusId"]) for o in obs_rows
                if o.get("ring") not in LIVE_RING_EXCLUDED}
    missing = sorted(ring_ids - tids)
    if missing:
        failures.append(f"[derived-join] {len(missing)}/{len(ring_ids)} live-ring ids have "
                        f"NO row in {os.path.basename(table)} (the join under-read): "
                        f"{missing[:20]}" + (f" (+{len(missing)-20} more)"
                                             if len(missing) > 20 else ""))
    elif ring_ids:
        warnings.append(f"[report] derived-join complete: {len(ring_ids)}/{len(ring_ids)} "
                        f"live-ring ids present")
    # (b) catch-all budget + (d) UNJUDGED ≠ bucket
    bfield = bucket or next((f for f in ("bucket", "family", "primary_family", "class",
                                         "category", "tag") if f in rows[0]), None)
    if bfield:
        vals = [(str(r.get(key)), str(r.get(bfield) or "")) for r in rows]
        catch = [c for c, v in vals if not v or CATCHALL.match(v)]
        frac = len(catch) / len(vals)
        if frac > budget:
            failures.append(f"[derived-catchall] {bfield}: {len(catch)}/{len(vals)} rows "
                            f"({frac:.0%}) in the empty/catch-all bucket > budget "
                            f"{budget:.0%} — STOP; bucket dump: {catch[:50]}"
                            + (f" (+{len(catch)-50} more)" if len(catch) > 50 else ""))
        else:
            warnings.append(f"[report] catch-all '{bfield}': {len(catch)}/{len(vals)} "
                            f"({frac:.0%}) within budget {budget:.0%}")
        unj = [c for c, v in vals if tiers.get(c) is None and v
               and v.upper() not in ("UNJUDGED", "MISSING", "NONE")]
        if unj:
            failures.append(f"[derived-unjudged] {len(unj)} UNJUDGED ids carry a semantic "
                            f"'{bfield}' value (pipeline state absorbed into a verdict) "
                            f"e.g. {unj[:5]}")
    else:
        warnings.append("[derived] no bucket field found — catch-all budget UNCHECKED "
                        "(name one with --bucket)")
    # (c) provenance: inputs actually consumed, re-counted now
    cands = [re.sub(r"\.jsonl$", "", table) + ".meta.json", table + ".meta.json"]
    metap = next((p for p in cands if os.path.exists(p)), None)
    if metap is None:
        failures.append(f"[derived-provenance] no sidecar {os.path.basename(cands[0])} — a "
                        f"derived table must record inputs ACTUALLY CONSUMED: "
                        f'{{"inputs": {{"<path>": <n_rows_read>}}}}')
    else:
        inputs = (json.load(open(metap)) or {}).get("inputs") or {}
        if not inputs:
            failures.append(f"[derived-provenance] {os.path.basename(metap)}: 'inputs' "
                            f"missing/empty — provenance line required")
        for ip, n in inputs.items():
            ap = ip if os.path.isabs(ip) else os.path.join(run, ip)
            if not os.path.exists(ap):
                failures.append(f"[derived-provenance] consumed input {ip} no longer exists")
            elif isinstance(n, int):
                now = sum(1 for l in open(ap) if l.strip())
                if now != n:
                    failures.append(f"[derived-provenance] {ip}: consumed {n} rows but the "
                                    f"file now has {now} — under-reading glob or stale "
                                    f"derivation; re-derive")
        if inputs:
            warnings.append("[report] provenance: consumed " +
                            ", ".join(f"{p} ({n})" for p, n in inputs.items()))
    return failures, warnings


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if sys.argv[1] == "derived":
        opt = lambda flag, default, cast=str: (cast(sys.argv[sys.argv.index(flag) + 1])
                                               if flag in sys.argv else default)
        failures, warnings = validate_derived(
            sys.argv[2], sys.argv[3], key=opt("--key", "corpusId"),
            bucket=opt("--bucket", None), budget=opt("--budget", 0.10, float))
    else:
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
