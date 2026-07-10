"""report_gate.py — [T] gate at report close: produce-X-gate-X applied to the report itself.

Exists because prose-only requirements measurably decay (a run's report traced 66% of its
numeric claims vs a sibling's 87%, and dropped the boundary language its own verdict file
contained). Run AFTER building the report, BEFORE presenting it; fix and rerun until PASS.

Checks (claims = numbers >= --min, excluding years and id-length ints):
  1. NUMBER TRACING — every number >= --min in report prose must appear in a data file
     (report/data/* or the run's jsonl/json/csv). Threshold: >= 85% traced.
  2. BOUNDARY LANGUAGE — the coverage section must contain explicit reader-facing boundary
     phrasing ("should not conclude" / "boundary" / "complete as-of").
  3. CHECKLIST — as-of date · refresh trigger · per-question "How performed" notes (>= number
     of answered questions) · working links present · no external CDN/script refs · data files
     exist and are non-empty.

Usage: python report_gate.py <report_dir> [--run <run_dir>] [--min 10] [--questions 4]
Exit 0 = PASS, 1 = FAIL (with the itemized reasons).
"""
from __future__ import annotations
import glob, json, os, re, sys


def _numbers_in(text):
    out = set()
    for m in re.finditer(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w.])", text):
        v = m.group(1).replace(",", "")
        try:
            f = float(v)
        except ValueError:
            continue
        out.add(v if "." in v else str(int(f)))
    return out


def _data_universe(report_dir, run_dir):
    nums = set()
    # req-11 means the PACKAGE carries the data homes — the report's own data/ dir (plus the
    # run's top-level canonical files as a secondary universe, at reduced credit via --run).
    paths = glob.glob(f"{report_dir}/data/*")
    if run_dir:
        paths += glob.glob(f"{run_dir}/*.json") + glob.glob(f"{run_dir}/*.csv")
    for p in paths:
        try:
            if os.path.getsize(p) > 30_000_000:
                continue
            nums |= _numbers_in(open(p, errors="ignore").read())
        except Exception:
            continue
    return nums, len(paths)


def gate(report_dir, run_dir=None, min_val=10, questions=4):
    fails, notes = [], []
    pages = [p for p in glob.glob(f"{report_dir}/*.html") + glob.glob(f"{report_dir}/*.md")
             if os.path.isfile(p)]
    if not pages:
        return ["no report pages found"], []
    text = " ".join(open(p, errors="ignore").read() for p in pages)
    # claims live in HUMAN-VISIBLE text only: strip scripts/styles/SVG, then every tag with
    # its attributes (chart coordinates and href ids are not prose claims)
    prose = re.sub(r"<script.*?</script>|<style.*?</style>|<svg.*?</svg>", " ", text, flags=re.S)
    prose = re.sub(r"<[^>]+>", " ", prose)

    # 1. number tracing
    universe, nfiles = _data_universe(report_dir, run_dir)
    claims = {n for n in _numbers_in(prose)
              if float(n) >= min_val and n not in ("19", "20", "202")  # bare year fragments
              and not re.fullmatch(r"(19|20)\d\d", n)
              and len(n.split(".")[0]) < 6}  # 6+ digit ints = corpusIds/DOIs in links, not claims
    traced = {n for n in claims if n in universe}
    rate = len(traced) / len(claims) if claims else 1.0
    notes.append(f"number tracing: {len(traced)}/{len(claims)} = {rate:.0%} (vs {nfiles} data files)")
    if rate < 0.85:
        untraced = sorted(claims - traced, key=float, reverse=True)[:15]
        fails.append(f"number tracing {rate:.0%} < 85% — untraced: {untraced}")

    # 2. boundary language — the reader-facing framing specifically (a report that only says
    # "complete as-of" passed a human review as DEFICIENT; the should-not-conclude framing is
    # the requirement)
    if not re.search(r"should\s+not\s+conclude|not\s+a\s+complete\s+enumeration|do(es)?\s+not\s+enumerate", prose, re.I):
        fails.append("no reader-facing boundary framing (what a reader should NOT conclude)")
    if not re.search(r"complete\s+as[- ]of|as[- ]of\s+\d{4}-", prose, re.I):
        fails.append("no as-of freshness statement")

    # 3. checklist
    if "refresh" not in prose.lower():
        fails.append("no refresh trigger")
    n_notes = len(re.findall(r"how\s+(this\s+was\s+)?performed", prose, re.I))
    notes.append(f"method notes found: {n_notes} (need >= {questions})")
    if n_notes < questions:
        fails.append(f"method notes {n_notes} < answered questions {questions}")
    if not re.search(r"semanticscholar\.org|arxiv\.org|doi\.org|aclanthology\.org", text):
        fails.append("no working paper links found")
    cdn = re.findall(r'(?:src|href)="https?://(?!api\.semanticscholar)[^"]+\.(?:js|css)"', text)
    if cdn:
        fails.append(f"external CDN refs (self-contained rule): {cdn[:3]}")
    data_files = [p for p in glob.glob(f"{report_dir}/data/*") if os.path.getsize(p) > 2]
    if not data_files:
        fails.append("report/data/ empty — prose aggregates have no data home")
    return fails, notes


if __name__ == "__main__":
    args = sys.argv[1:]
    run = args[args.index("--run") + 1] if "--run" in args else None
    mn = int(args[args.index("--min") + 1]) if "--min" in args else 10
    q = int(args[args.index("--questions") + 1]) if "--questions" in args else 4
    fails, notes = gate(args[0], run, mn, q)
    for n in notes:
        print("  ·", n)
    if fails:
        print("REPORT GATE: FAIL")
        for f in fails:
            print("  ✗", f)
        sys.exit(1)
    print("REPORT GATE: PASS")
