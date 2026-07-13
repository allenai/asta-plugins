"""sweep.py — [T] parallel driver for the fast/diligent find sweep (staged sweep policy, SKILL step 1).

Receipt: two independent cold runs reinvented this same driver — run4's ThreadPool `run_sweep.py`
over a `slug<TAB>query` TSV, and sa-cold2's `xargs -P4 run_sweeps.sh`. Both fanned
`asta literature find` across many angles, then ranked queries by their sidecar `not_judged` to
feed the diligent escalation gate. This is the canonical version: one TSV in, per-query provenance
files out, and the escalation signal (total sidecar `not_judged`, ranked per slug) printed at the
end — so the gate has its input without anyone re-reading their own sidecars by hand (the measured
failure: a run that never read its sidecars shipped an 85-90% head claim that measured ~44%).

Each line of <queries.tsv>:  slug<TAB>query[<TAB>mode]   (per-line mode overrides --mode; '#' comments).
Writes per query:  <run>/acq/astafind/<slug>.json  (+ <slug>.json.rejected.json sidecar)
  — the .json name is exactly what acquire.candidates_from_asta('acq/astafind/*.json') merges.

CLI:  python sweep.py <run_dir> <queries.tsv> [--mode fast|diligent] [--par 4] [--timeout 240]
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed


def read_queries(tsv_path, default_mode="fast"):
    """Parse the sweep TSV -> [(slug, query, mode)]. Blank lines and '#' comments skipped;
    a per-line third column overrides default_mode. Raises ValueError on a line missing slug|query
    (a malformed line must POP, not silently drop an angle from the sweep)."""
    out = []
    for n, raw in enumerate(open(tsv_path), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
            raise ValueError(f"{tsv_path}:{n}: expected 'slug<TAB>query[<TAB>mode]', got {line!r}")
        slug, query = parts[0].strip(), parts[1].strip()
        mode = parts[2].strip() if len(parts) > 2 and parts[2].strip() else default_mode
        out.append((slug, query, mode))
    return out


def _result_ids(path):
    """corpusIds in a find result file (same envelope acquire.candidates_from_asta reads)."""
    try:
        data = json.load(open(path))
    except Exception:
        return []
    rows = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    ids = []
    for r in rows or []:
        cid = str(r.get("corpusId") or "")
        if cid and cid != "None":
            ids.append(cid)
    return ids


def _sidecar_stats(path):
    """(not_judged, total_hits) from a `--include-rejected` sidecar, tolerant of shape.
    Prefers explicit int fields anywhere in the doc; falls back to the length of a sampled
    dropped-docs list. (None, None) when the sidecar is absent/unreadable — the caller reports
    not_judged as '?' rather than pretending it saw zero drops."""
    if not os.path.exists(path):
        return None, None
    try:
        data = json.load(open(path))
    except Exception:
        return None, None

    def dig(d, key):
        if isinstance(d, dict):
            if isinstance(d.get(key), int):
                return d[key]
            for v in d.values():
                r = dig(v, key)
                if r is not None:
                    return r
        return None

    nj = dig(data, "not_judged")
    th = dig(data, "total_hits")
    if nj is None and isinstance(data, dict):
        for k in ("rejected", "sample", "not_judged_sample", "docs"):
            if isinstance(data.get(k), list):
                nj = len(data[k])
                break
    return nj, th


def _run_one(run_dir, slug, query, mode, timeout):
    outdir = os.path.join(run_dir, "acq", "astafind")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{slug}.json")
    cmd = ["asta", "literature", "find", query, "-o", out, "--mode", mode,
           "--include-rejected", "sample", "--timeout", str(timeout)]
    rec = {"slug": slug, "query": query, "mode": mode, "out": out,
           "status": "ok", "count": 0, "ids": [], "not_judged": None, "total_hits": None, "error": None}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
        if p.returncode != 0:
            rec["status"] = "failed"
            rec["error"] = (p.stderr or p.stdout or "nonzero exit").strip()[:200]
    except subprocess.TimeoutExpired:
        rec["status"] = "timeout"
        rec["error"] = f"exceeded {timeout + 60}s wall clock"
    except Exception as e:                       # keep the fleet moving; record and continue
        rec["status"] = "failed"
        rec["error"] = str(e)[:200]
    rec["ids"] = _result_ids(out)
    rec["count"] = len(rec["ids"])
    rec["not_judged"], rec["total_hits"] = _sidecar_stats(out + ".rejected.json")
    if rec["status"] == "ok" and not os.path.exists(out):
        rec["status"], rec["error"] = "no-output", "command exited 0 but wrote no result file"
    return rec


def run_sweep(run_dir, queries, mode="fast", par=4, timeout=240, stream=sys.stdout):
    """Fan `queries` across `par` workers; stream a per-query completion line; return records."""
    lock = threading.Lock()
    records, total, done = [], len(queries), 0
    with ThreadPoolExecutor(max_workers=par) as ex:
        futs = [ex.submit(_run_one, run_dir, s, q, m, timeout) for s, q, m in queries]
        for fut in as_completed(futs):
            rec = fut.result()
            with lock:
                done += 1
                nj = rec["not_judged"]
                njs = "?" if nj is None else nj
                tail = "" if rec["status"] == "ok" else f"  [{rec['status'].upper()}] {rec['error'] or ''}"
                print(f"[{done}/{total}] {rec['slug']:<24} {rec['mode']:<8} "
                      f"{rec['count']:>4} hits  not_judged={njs}{tail}", file=stream, flush=True)
                records.append(rec)
    return records


def print_summary(records, stream=sys.stdout):
    """Merge-ready summary: unique-id total, per-slug yields ranked by not_judged (= the
    escalation ranking), total not_judged (the escalation SIGNAL), and the failure re-run list."""
    uniq = set()
    for r in records:
        uniq.update(r.get("ids") or [])
    total_nj = sum(r["not_judged"] for r in records if isinstance(r["not_judged"], int))
    ok = [r for r in records if r["status"] == "ok"]
    bad = [r for r in records if r["status"] != "ok"]
    print("\n=== sweep summary (merge-ready) ===", file=stream)
    print(f"queries: {len(records)}   ok: {len(ok)}   failed/timeout: {len(bad)}", file=stream)
    print(f"total unique corpusIds across result files: {len(uniq)}", file=stream)
    print(f"total sidecar not_judged (ESCALATION SIGNAL): {total_nj}", file=stream)
    print("per-slug yields (ranked by not_judged — escalate the top slice to --mode diligent):", file=stream)
    for r in sorted(records, key=lambda x: -(x["not_judged"] or 0)):
        nj = r["not_judged"]
        njs = "?" if nj is None else nj
        print(f"  {r['slug']:<24} hits={r['count']:>4}  not_judged={str(njs):<6} {r['status']}", file=stream)
    if bad:
        print("failures (rerun these):", file=stream)
        for r in bad:
            print(f"  {r['slug']}: {r['status']} — {r['error']}", file=stream)
    print("\nnext: acquire.candidates_from_asta('acq/astafind/*.json') -> merge_candidates -> validate.py;"
          "\n      then escalate the top not_judged slice (~25-30%) to --mode diligent (SKILL step 1 gate).",
          file=stream)


def _parse_args(argv):
    pos, opts = [], {"--mode": "fast", "--par": "4", "--timeout": "240"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in opts:
            opts[a] = argv[i + 1]
            i += 2
        else:
            pos.append(a)
            i += 1
    if len(pos) < 2:
        sys.exit("usage: python sweep.py <run_dir> <queries.tsv> "
                 "[--mode fast|diligent] [--par 4] [--timeout 240]")
    return pos[0], pos[1], opts


if __name__ == "__main__":
    run_dir, tsv, opts = _parse_args(sys.argv[1:])
    if shutil.which("asta") is None:
        sys.exit("ERROR: `asta` CLI not on PATH. Install/update it via the asta-cli skill, then retry.")
    queries = read_queries(tsv, default_mode=opts["--mode"])
    if not queries:
        sys.exit(f"no queries in {tsv}")
    recs = run_sweep(run_dir, queries, mode=opts["--mode"],
                     par=int(opts["--par"]), timeout=int(opts["--timeout"]))
    print_summary(recs)
