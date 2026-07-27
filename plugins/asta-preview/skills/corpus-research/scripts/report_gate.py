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
  4. POOLED-CLAIM WARRANTS — report/data/synthesis.json sidecar required (receipt: keystats
     gate-gaming — stats can be planted to satisfy tracing): one entry per pooled claim
     {claim, because, unless, basis_note}; every family/axis stat surfaced in keystats/charts
     (axis rows + family/axis-named keys) must be covered by an entry. Missing sidecar or
     uncovered stat = FAIL. (Doctrine home: references/deliverables.md synthesis-pass section.)
  5. COST-ACTUAL — the round-manifest (--run dir or the report dir's parent) or keystats must
     carry a STRUCTURED cost_actual: numeric content (tokens/$) or the subscription-lane form
     (turns + subagents + fetch counts + compute-tokens-eval-side). Absent or prose-only =
     FAIL (receipt: cost-actual failed live — cost was reconstructed eval-side).

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


_POOLED_KEY = re.compile(r"axis|axes|famil|stance|disagree", re.I)
_WARRANT_FIELDS = ("claim", "because", "unless", "basis_note")


def _canon(s):
    """Match key for stat-name coverage: lowercase, -/_// as spaces, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[-_/]", " ", s.lower())).strip()


def _pooled_stats(report_dir):
    """The family/axis stats a report SURFACES to the reader: axis names in chart rows, row
    labels of family/axis-named chart groups, and family/axis-named keystats keys. Mechanical
    — these are the pooled aggregates the warrants sidecar must cover."""
    out = set()
    parse_fails = []
    for p in (f"{report_dir}/data/keystats.json", f"{report_dir}/data/charts.json"):
        try:
            d = json.load(open(p))
        except FileNotFoundError:
            continue
        except Exception as e:
            # never degrade silently: a corrupt data file would otherwise reduce this
            # check to "sidecar exists" (the catch-all anti-pattern)
            parse_fails.append(f"{os.path.basename(p)}: {e}")
            continue
        if not isinstance(d, dict):
            continue
        for k, v in d.items():
            if isinstance(v, list):
                for row in v:
                    if not isinstance(row, dict):
                        continue
                    if isinstance(row.get("axis"), str):
                        out.add(row["axis"])
                    elif _POOLED_KEY.search(k) and isinstance(row.get("label"), str):
                        out.add(row["label"])
            elif _POOLED_KEY.search(k):
                out.add(k)
    return out, parse_fails


def _cost_actual_ok(v):
    """Structured cost_actual only: a bare number, or a dict with numeric leaves keyed
    tokens/cost/usd/$ (numeric lane), or the subscription-lane form — numeric turns +
    subagents/workers + fetch counts plus a compute-tokens key. Prose strings never pass."""
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v > 0  # a bare 0 is a placeholder, not an accounting
    if not isinstance(v, dict):
        return False  # string/list = prose-only, not structured
    leaves = {}

    def walk(d, pre=""):
        for k, x in d.items():
            kk = f"{pre}{k}".lower()
            if isinstance(x, bool):
                continue
            if isinstance(x, (int, float)):
                leaves[kk] = x
            elif isinstance(x, dict):
                walk(x, kk + ".")
    walk(v)
    if any(re.search(r"token|cost|usd|dollar|\$", k) and val > 0
           for k, val in leaves.items()):
        return True  # numeric lane: tokens/$ with a real (>0) number
    sub = (r"turn", r"subagent|worker|agent", r"fetch")
    return (all(any(re.search(pat, k) for k in leaves) for pat in sub)
            and any("token" in k for k in leaves))  # subscription lane, nested-symmetric


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
    if not re.search(r"should\s+not\s+(conclude|read)|not\s+a\s+complete\s+enumeration|not\s+enumerated|do(es)?\s+not\s+(enumerate|read\s+the\s+corpus\s+as\s+complete)|sampled,?\s+not\s+enumerated", prose, re.I):
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
    # package-escape: relative links out of the report dir break the moment the package is
    # shared (measured: ../../vault/... links shipped to a colleague)
    esc = re.findall(r'(?:src|href)="(\.\./[^"]+)"', text)
    if esc:
        fails.append(f"links escape the package (must be self-contained for sharing): {esc[:3]}")
    # S2 canonical link form: api.semanticscholar.org/CorpusId:<id> is the documented redirect;
    # the www./paper/CorpusID: variant is undocumented (measured: shipped once, user-caught)
    badform = re.findall(r'www\.semanticscholar\.org/paper/CorpusI[dD]:\d+', text)
    if badform:
        fails.append(f"non-canonical S2 links (use api.semanticscholar.org/CorpusId:<id>): {badform[:3]}")
    data_files = [p for p in glob.glob(f"{report_dir}/data/*") if os.path.getsize(p) > 2]
    if not data_files:
        fails.append("report/data/ empty — prose aggregates have no data home")

    # 4. pooled-claim warrants — the synthesis.json sidecar (one entry per pooled claim);
    # numbers can be planted into keystats to satisfy tracing (measured), so every surfaced
    # family/axis stat must also carry a warranted claim {claim, because, unless, basis_note}
    sp = f"{report_dir}/data/synthesis.json"
    entries = None
    if os.path.isfile(sp):
        try:
            loaded = json.load(open(sp))
            entries = loaded if isinstance(loaded, list) and loaded else None
        except Exception:
            entries = None
    surfaced, parse_fails = _pooled_stats(report_dir)
    for pf in parse_fails:
        fails.append(f"pooled-claim warrants: data file unparseable ({pf}) — cannot "
                     f"enumerate surfaced stats; fix the file (check 3 only tests non-empty)")
    if entries is None and not surfaced:
        notes.append("pooled-claim warrants: no surfaced family/axis stats and no sidecar — "
                     "vacuously OK (an empty synthesis.json [] is also accepted)")
    elif entries is None:
        fails.append("pooled-claim warrants: report/data/synthesis.json missing (or not a "
                     "JSON list) — one entry per pooled claim "
                     "{claim, because, unless, basis_note}")
    else:
        bad = [i for i, e in enumerate(entries)
               if not isinstance(e, dict) or any(
                   not (isinstance(e.get(k), str) and e[k].strip()) for k in _WARRANT_FIELDS)]
        if bad:
            fails.append(f"pooled-claim warrants: {len(bad)} synthesis.json entries missing "
                         f"required fields {list(_WARRANT_FIELDS)} (rows {bad[:10]})")
        # PER-ENTRY matching (gate-gaming receipt: one entry name-dropping every axis in
        # prose must NOT cover them all) — a stat is covered only if some entry's CLAIM
        # names it.
        claims = [_canon(str(e.get("claim") or "")) for e in entries if isinstance(e, dict)]
        uncovered = sorted(s for s in surfaced if not any(_canon(s) in c for c in claims))
        notes.append(f"pooled-claim warrants: {len(entries)} entries cover "
                     f"{len(surfaced) - len(uncovered)}/{len(surfaced)} surfaced "
                     f"family/axis stats")
        if uncovered:
            fails.append(f"pooled-claim warrants: surfaced family/axis stats with NO "
                         f"synthesis entry: {uncovered[:10]}")

    # 5. cost-actual — a structured cost record must ship with the round, mechanically
    # checkable (prose decays; a live run's cost had to be reconstructed eval-side)
    cost, cost_home = None, None
    for p in ([f"{run_dir}/round-manifest.json"] if run_dir else []) + [
            f"{os.path.dirname(os.path.abspath(report_dir))}/round-manifest.json",
            f"{report_dir}/data/keystats.json"]:
        if os.path.isfile(p):
            try:
                v = json.load(open(p)).get("cost_actual")
            except Exception:
                continue
            if v is not None:
                cost, cost_home = v, p
                break
    if cost is None:
        fails.append("cost_actual absent — the round-manifest (or keystats) must carry it: "
                     "numeric tokens/$ or the subscription-lane form (turns + subagents + "
                     "fetch counts + compute-tokens-eval-side)")
    elif not _cost_actual_ok(cost):
        fails.append(f"cost_actual prose-only/unstructured in {cost_home} — need numeric "
                     f"tokens/$ or the subscription-lane form (turns + subagents + fetch "
                     f"counts + compute-tokens-eval-side)")
    else:
        notes.append(f"cost_actual: structured ({cost_home})")
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
