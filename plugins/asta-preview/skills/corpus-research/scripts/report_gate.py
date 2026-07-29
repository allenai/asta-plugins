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

Presentation-layer checks (the presentation layer earlier gates left ungated — each fires only
when its structure is present, so legacy artifacts degrade to loud fails, never crashes):
  6. MACHINERY-BACKSTAGE — internal vocab (workspace file names, schema field names like
     stop_kind/judged_by, shard/salt/gate names, AX-* tags) in VISIBLE narrative = FAIL,
     listing the offending spans. Exempt homes: <details> blocks, method-note blocks,
     blockquotes (the paper's words), code, and package/file-listing/method sections.
  7. NO-VERBATIM-DUPLICATION — a <details> block repeating its preceding paragraph verbatim
     (>=200-char overlap) = FAIL ("Claim as shipped:" x17 measured).
  8. CATALOG RENDERING — mid-word/mechanical truncation (word + attached ellipsis at a cell/
     line boundary) · promised affordances must exist ("sortable" with no sort mechanism in
     any page's scripts/handlers = FAIL) · a single page over ~30k visible chars with no nav
     element = FAIL.
  9. PER-QUESTION SPAN FLOORS — every question-shaped section (Q<n>/Question <n> heading)
     must carry >= --span-floor verbatim spans (blockquotes/long quotes) IN its prose;
     per-question counts always reported (receipt: one question's concentration carried a
     report while Q1-Q3+coverage shipped 0 spans).
 10. EMPTY≠OTHER — a synthesis.json entry that decomposes a stat with null/unprocessed/
     missing language while NO shipped aggregate carries that class as a distinct key/label
     = FAIL (twice-ruled: null/unprocessed is a separate class in every aggregate; receipt:
     Other=20 shipped while its synthesis entry said 7+13).
 11. AXIS STRENGTH PROFILES — every surfaced axis record ships a PER-SIDE strength-v1
     profile ({side: {n, strong, ...}} on the row or in data/strength.json; compute with
     scripts/strength.py). Stratum is a slice label, never a disqualifier. When
     support_kind is recorded anywhere in the shipped data (A3), each side's profile must
     also carry its support-kind MIX (by_support_kind; open vocabulary — literal strings,
     never a closed enum) — recorded nowhere = legacy, noted. Rows that DO carry
     support_kind must also carry a non-empty basis.strength_note (the always-written
     nuance carrier, same convention as because/unless); rows with neither = legacy, pass.
 12. PLACEHOLDER SIDECAR — an all-zero *mix* block (e.g. fit_mix with every count 0) in a
     report data file = FAIL (a mix that counted nothing is a placeholder, not a measurement).
 13. CLOSING-REBUILD CARRIED — a round-manifest, when present, must carry closing_rebuild
     {regression_gate_count, residual_unverified_spans} (both printed by vault.py rebuild;
     receipt: a closing-rebuild regression gate fired unreported — silent absorption). NEW
     rounds only by construction: no round-manifest = unchecked here (cost check 5 already
     fails a manifest-less new round).

Usage: python report_gate.py <report_dir> [--run <run_dir>] [--min 10] [--questions 4]
                             [--span-floor 1]
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
    — these are the pooled aggregates the warrants sidecar must cover. Also returns the AXIS
    ROWS themselves ({axis_name: row}) — check 11 requires a per-side strength profile on
    every axis record."""
    out = set()
    axes = {}
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
                        axes.setdefault(row["axis"], row)
                    elif _POOLED_KEY.search(k) and isinstance(row.get("label"), str):
                        out.add(row["label"])
            elif _POOLED_KEY.search(k):
                out.add(k)
    return out, axes, parse_fails


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


# ---------------------------------------------------------- presentation-layer helpers (checks 6-14)

# section headings whose CONTENT is exempt from the machinery-backstage scan (the sanctioned
# homes for internal vocabulary: method notes, package/file listings, appendices)
_EXEMPT_HEAD = re.compile(
    r"\b(?:packages?|artifacts?|files?|appendix|appendices|methods?|downloads?)\b", re.I)
# word-bounded: "Methodological disagreements" and "strength profiles" must NOT self-exempt
# (measured gaming hole: substring 'method'/'file' exempted doctrine-mandated sections)

# the internal-vocab denylist (machinery-backstage). Scanned over VISIBLE NARRATIVE only — the
# reader's prose speaks the reader's vocabulary; this vocabulary belongs in contract
# artifacts, method notes and the details register (deliverables.md: machinery backstage).
_MACHINERY = (
    ("workspace-file", re.compile(
        r"\b[\w-]+\.(?:jsonl|db)\b"
        r"|\b(?:observations|candidates|standardized-relevance|extractions?|keystats|"
        r"synthesis|charts|salts|thread|round-manifest|vault|strength)\.json\b", re.I)),
    ("schema-field", re.compile(
        r"\b(?:stop_kind|judged_by|claim_kind|claim_type|ladder_rung|ladder_target|"
        r"basis_note|scope_flag|primary_family|relevance_tier|fit_mix|support_kind|"
        r"strength_note|text_source|source_tier|round_order|corpusId_raw)\b")),
    ("schema-field", re.compile(       # bare 'fit' is normal English; the FIELD form is not
        r"\bfit\s*[:=]\s*['\"“]?(?:explicit|rephrased|reframed|stretch|legacy)", re.I)),
    ("shard/salt", re.compile(
        r"\bshard(?:s|ed|ing)?\b"
        r"|\bsalts?\b[^\n.]{0,60}?(?:judg|calibrat|plant)"
        r"|(?:judg|calibrat|plant)[^\n.]{0,60}?\bsalts?\b", re.I)),
    ("gate-name", re.compile(
        r"\b\w+_gate\b|\bgate_\w+\b"
        r"|\b(?:merge|regression|support|report|orientation)[- ]gate\b", re.I)),
    ("AX-tag", re.compile(r"\b(?:AX|INC)-\d+\b")),
)

# promised affordance -> the mechanism that must exist somewhere in the package's pages
_AFFORDANCES = (
    (re.compile(r"\bsortable\b|\bsort(?:ed)?\s+by\s+click|\bclick[^.\n]{0,30}?\bto\s+sort\b",
                re.I), re.compile(r"sort", re.I), "sorting"),
    (re.compile(r"\bfilterable\b", re.I), re.compile(r"filter", re.I), "filtering"),
    (re.compile(r"\bsearchable\b", re.I), re.compile(r"search|filter", re.I), "search"),
)

_NAV_CHARS = 30_000    # visible chars beyond which a single page needs in-page navigation
_QHEAD = re.compile(r"\bQ(?:uestion\s*)?(\d+)\b", re.I)
# null-class decomposition language ADJACENT to a number (conservative: both required)
_NULL_ADJ = re.compile(
    r"\d[^.;]{0,40}?\b(?:null|unprocessed|un-?judged|not[- ]yet[- ]processed|unlabel\w*|"
    r"no[- ]data|missing)\b"
    r"|\b(?:null|unprocessed|un-?judged|not[- ]yet[- ]processed|unlabel\w*|no[- ]data|"
    r"missing)\b[^.;]{0,40}?\d", re.I | re.S)
_NULL_CLASS = re.compile(r"\b(?:null|unprocessed|un-?judged|not[- ]yet[- ]processed|"
                         r"unlabel\w*|no[- ]data|missing)\b", re.I)


def _tagstrip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _visible_narrative(raw):
    """The text a reader actually READS, for the machinery-backstage scan: strips script/
    style/svg, <details> blocks (the audit register), blockquotes (the paper's words, not
    ours), code, method-note blocks, and package/file-listing/method SECTIONS (heading to
    next heading) — the exempt homes internal vocabulary is allowed to live in."""
    t = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<svg.*?</svg>", " ", raw)
    t = re.sub(r"(?is)<details.*?</details>|<blockquote.*?</blockquote>", " ", t)
    # HTML method-note blocks stripped AS BLOCKS (measured false-positive: a long method
    # div's file/field mentions survived the text-level fallback below because the block
    # had no blank line within its window). Method divs don't nest in our reports.
    t = re.sub(r'(?is)<(div|p|section)[^>]+class="[^"]*method[^"]*"[^>]*>.*?</\1>', " ", t)
    t = re.sub(r"(?s)```.*?```", " ", t)                       # md fenced code
    t = re.sub(r"`[^`\n]+`", " ", t)                           # md inline code
    t = re.sub(r"(?m)^\s*>.*$", " ", t)                        # md blockquotes
    kept = []
    for seg in re.split(r"(?im)(?=<h[1-6][^>]*>|^#{1,6}\s)", t):
        m = re.match(r"(?is)<h[1-6][^>]*>(.*?)</h[1-6]>", seg) or re.match(
            r"(?m)^#{1,6}\s+([^\n]*)", seg)
        if m and _EXEMPT_HEAD.search(_tagstrip(m.group(1))):
            continue
        kept.append(seg)
    t = re.sub(r"<[^>]+>", " ", " ".join(kept))
    # method-note blocks not caught by a heading: marker to the next blank line
    t = re.sub(r"(?is)how\s+(?:this\s+was\s+|it\s+was\s+)?performed.{0,1600}?(?:\n\s*\n|(?=how\s+performed)|$)",
               " ", t)
    return t


def _count_spans(chunk):
    """Verbatim spans in one section's RAW text: blockquotes (html + md groups), <q> tags,
    and long quoted strings (>=40 chars) in the tag-stripped text."""
    n = (len(re.findall(r"(?i)<blockquote", chunk))
         + len(re.findall(r"(?m)^(?:\s*>\s?\S.*\n?)+", chunk))
         + len(re.findall(r"(?i)<q\b", chunk)))
    flat = re.sub(r"<[^>]+>", " ",
                  re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", chunk))
    n += len(re.findall(r"“[^”]{40,600}”", flat))
    n += len(re.findall(r'(?<!\w)"[^"\n]{40,600}"', flat))
    return n


def _headings(raw):
    """(start, end, level, text) for html + md headings, position-sorted."""
    heads = [(m.start(), m.end(), int(m.group(1)), _tagstrip(m.group(2)))
             for m in re.finditer(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>", raw)]
    heads += [(m.start(), m.end(), len(m.group(1)), m.group(2).strip())
              for m in re.finditer(r"(?m)^(#{1,6})\s+(.+)$", raw)]
    return sorted(heads)


def _num_leaves(x):
    out = []
    if isinstance(x, dict):
        for v in x.values():
            out += _num_leaves(v)
    elif isinstance(x, list):
        for v in x:
            out += _num_leaves(v)
    elif isinstance(x, (int, float)) and not isinstance(x, bool):
        out.append(x)
    return out


def _strength_profile_ok(v):
    """A per-side strength-v1 profile: {side: {n, strong, ...}} with >=1 side and numeric
    n/strong per side (the reader sees not just how many, but how solid)."""
    if not isinstance(v, dict) or not v:
        return False
    sides = {k: s for k, s in v.items() if isinstance(s, dict)}
    return bool(sides) and all(
        isinstance(s.get("n"), (int, float)) and not isinstance(s.get("n"), bool)
        and isinstance(s.get("strong"), (int, float)) and not isinstance(s.get("strong"), bool)
        and s["n"] > 0 and s["strong"] <= s["n"]     # anti name-drop: a hand-typed profile
        for s in sides.values())                     # must at least be internally coherent


def gate(report_dir, run_dir=None, min_val=10, questions=4, span_floor=1):
    fails, notes = [], []
    pages = [p for p in glob.glob(f"{report_dir}/*.html") + glob.glob(f"{report_dir}/*.md")
             if os.path.isfile(p)]
    if not pages:
        return ["no report pages found"], []
    page_texts = {p: open(p, errors="ignore").read() for p in pages}
    text = " ".join(page_texts.values())
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
    surfaced, axes, parse_fails = _pooled_stats(report_dir)
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

    # ---- 6-14: presentation-layer checks. Each fires only when its structure is
    # present (no details blocks / question headings / axes = vacuous or noted), so legacy
    # artifacts re-gated here degrade to LOUD fails, never crashes.

    # 6. MACHINERY-BACKSTAGE — internal vocab in the reader's prose (measured: a report's
    # narrative read "round-X / job-X"; internal names belong in method notes + contracts)
    hits = []
    for pth, raw in page_texts.items():
        vis = _visible_narrative(raw)
        for label, rx in _MACHINERY:
            for m in rx.finditer(vis):
                ctx = re.sub(r"\s+", " ", vis[max(0, m.start() - 35):m.end() + 35]).strip()
                hits.append(f"[{label}] {os.path.basename(pth)}: …{ctx}…")
    if hits:
        fails.append(f"machinery-backstage: {len(hits)} internal-vocab span(s) in VISIBLE "
                     f"narrative (details/method-notes/package-listing are the exempt homes; "
                     f"the reader's prose speaks the reader's vocabulary): "
                     + " | ".join(hits[:10])
                     + (f" (+{len(hits) - 10} more)" if len(hits) > 10 else ""))

    # 7. NO-VERBATIM-DUPLICATION — a details block restating its preceding paragraph
    # verbatim doubles the page and buries the audit register ("Claim as shipped:" x17)
    dupes = []
    for pth, raw in page_texts.items():
        for m in re.finditer(r"(?is)<details[^>]*>(.*?)</details>", raw):
            d = _tagstrip(re.sub(r"(?is)<summary.*?</summary>", " ", m.group(1)))
            if len(d) < 200:
                continue
            pre = _tagstrip(raw[max(0, m.start() - 3000):m.start()])
            for i in range(0, max(1, len(d) - 199), 40):
                w = d[i:i + 200]
                if len(w) >= 200 and w in pre:
                    dupes.append(f"{os.path.basename(pth)}: {w[:80]!r}…")
                    break
    if dupes:
        fails.append(f"verbatim duplication: {len(dupes)} <details> block(s) repeat their "
                     f"preceding paragraph verbatim (>=200-char overlap) — the collapsed "
                     f"block holds the AUDIT, never a copy of the narrative: "
                     + " · ".join(dupes[:5]))

    # 8. CATALOG RENDERING — truncation · promised affordances · nav on long pages
    trunc = []
    for pth, raw in page_texts.items():
        cuts = (re.findall(r"[\w’'](?:…|\.\.\.)\s*(?=<)", raw) if pth.endswith(".html")
                else re.findall(r"(?m)[\w’'](?:…|\.\.\.)\s*(?:\||$)", raw))
        if len(cuts) >= 3:
            exs = [re.sub(r"\s+", " ", raw[max(0, m.start() - 28):m.end()])
                   for m in list(re.finditer(r"[\w’']+(?:…|\.\.\.)", raw))[:4]]
            trunc.append(f"{os.path.basename(pth)}: {len(cuts)} cut(s) e.g. {exs}")
    if trunc:
        fails.append("catalog rendering: mid-word/mechanical truncation (word + attached "
                     "ellipsis at a cell/line boundary — render the full string, or cut at "
                     "a word boundary with the full text reachable): " + " · ".join(trunc))
    mech_text = " ".join(
        " ".join(re.findall(r"(?is)<script[^>]*>(.*?)</script>", raw))
        + " " + " ".join(re.findall(r'\bon\w+\s*=\s*"([^"]*)"', raw))
        + " " + " ".join(re.findall(r"(?i)<input[^>]*>|data-sort[^\s=>]*", raw))
        for raw in page_texts.values())
    for pth, raw in page_texts.items():
        flat = _tagstrip(re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw))
        for promise_rx, mech_rx, name in _AFFORDANCES:
            pm = promise_rx.search(flat)
            if pm and not mech_rx.search(mech_text):
                fails.append(f"catalog rendering: {os.path.basename(pth)} promises "
                             f"{pm.group(0)!r} but NO {name} mechanism exists in any page "
                             f"(no script/handler/input) — a promised affordance must work "
                             f"or the promise goes")
        if len(flat) > _NAV_CHARS:
            has_nav = (re.search(r"(?i)<nav\b|table of contents|jump to", raw)
                       or len(re.findall(r'href="#[^"]+"', raw)) >= 3
                       or len(re.findall(r"\]\(#[^)]+\)", raw)) >= 3)
            if not has_nav:
                fails.append(f"catalog rendering: {os.path.basename(pth)} is "
                             f"{len(flat):,} visible chars with NO nav element (no <nav>, "
                             f"<3 in-page anchors, no TOC) — a single page over "
                             f"~{_NAV_CHARS:,} chars needs in-page navigation")

    # 9. PER-QUESTION SPAN FLOORS — report prose CARRIES spans, per answered question
    # (deliverables req 4; receipt: one question's concentration carried a whole report)
    qcounts = {}
    for pth, raw in page_texts.items():
        heads = _headings(raw)
        for i, (s, e, lvl, txt) in enumerate(heads):
            qm = _QHEAD.search(txt)
            if not qm:
                continue
            end = len(raw)
            for s2, _e2, lvl2, txt2 in heads[i + 1:]:
                if lvl2 <= lvl or _QHEAD.search(txt2):
                    end = s2
                    break
            q = f"Q{int(qm.group(1))}"
            qcounts[q] = qcounts.get(q, 0) + _count_spans(raw[e:end])
    if qcounts:
        notes.append("per-question verbatim spans: "
                     + " ".join(f"{q}={n}" for q, n in sorted(qcounts.items()))
                     + f" (floor {span_floor})")
        low = [q for q, n in sorted(qcounts.items()) if n < span_floor]
        if low:
            fails.append(f"per-question span floor: "
                         + ", ".join(f"{q} ({qcounts[q]} span(s))" for q in low)
                         + f" below floor {span_floor} — every answered question section "
                         f"carries verbatim spans IN its prose, not only in data files")
    else:
        notes.append("per-question span floor: no question-shaped headings (Q<n>) found — "
                     "unchecked (applies to question-sectioned reports)")

    # 10. EMPTY≠OTHER — no shipped aggregate contradicted by its own synthesis entry
    # (twice-ruled; receipt: Other=20 shipped while the synthesis entry said 7+13)
    if entries:
        labels = set()
        for p in (f"{report_dir}/data/keystats.json", f"{report_dir}/data/charts.json"):
            try:
                d = json.load(open(p))
            except Exception:
                continue

            def _walk(x):
                if isinstance(x, dict):
                    for k, v in x.items():
                        labels.add(str(k))
                        _walk(v)
                elif isinstance(x, list):
                    for el in x:
                        _walk(el)
                elif isinstance(x, str):
                    labels.add(x)
            _walk(d)
        has_null_class = any(_NULL_CLASS.search(l) for l in labels)
        contra = [str(e.get("claim"))[:90] for e in entries if isinstance(e, dict)
                  and _NULL_ADJ.search(" ".join(str(e.get(k) or "")
                                                for k in _WARRANT_FIELDS))]
        if contra and not has_null_class:
            fails.append(f"empty≠other: {len(contra)} synthesis entr"
                         f"{'y' if len(contra) == 1 else 'ies'} decompose(s) a stat into a "
                         f"null/unprocessed class while NO shipped aggregate carries that "
                         f"class as a distinct key/label — ship the classes the synthesis "
                         f"states, never fold them into a catch-all: {contra[:4]}")
        elif contra:
            notes.append(f"empty≠other: {len(contra)} entr"
                         f"{'y carries' if len(contra) == 1 else 'ies carry'} null-class "
                         f"decomposition language; a distinct null-class key/label ships "
                         f"in the aggregates")

    # 11. AXIS STRENGTH PROFILES  — every surfaced axis record ships a per-side
    # strength-v1 profile; support-kind mix required only where support_kind is recorded
    if axes:
        prof_axes = {}
        spf = f"{report_dir}/data/strength.json"
        if os.path.isfile(spf):
            try:
                sl = json.load(open(spf))
                prof_axes = sl.get("axes", sl) if isinstance(sl, dict) else {}
            except Exception as exc:
                fails.append(f"axis strength: data/strength.json unparseable ({exc})")
        if not isinstance(prof_axes, dict):
            prof_axes = {}

        def _profile_for(name, row):
            for key in ("strength_profile", "strength", "per_side_strength"):
                if _strength_profile_ok(row.get(key)):
                    return row[key]
            cn = _canon(name)
            for k, v in prof_axes.items():
                # exact canon equality only — two-way substring let one strength.json key
                # satisfy multiple axes (measured gaming class)
                if cn == _canon(k) and _strength_profile_ok(v):
                    return v
            return None
        profs = {n: _profile_for(n, row) for n, row in axes.items()}
        missing = sorted(n for n, v in profs.items() if v is None)
        notes.append(f"axis strength profiles: {len(axes) - len(missing)}/{len(axes)} axis "
                     f"records carry a per-side strength-v1 profile")
        if missing:
            fails.append(f"axis strength: {len(missing)}/{len(axes)} axis records ship NO "
                         f"per-side strength-v1 profile ({{side: {{n, strong, ...}}}} on "
                         f"the axis row or in data/strength.json — compute with "
                         f"scripts/strength.py; stratum is a slice label, never a "
                         f"disqualifier): {missing[:8]}")
        # support-kind mix: required per side ONLY where support_kind is recorded
        sk_recorded = any(
            isinstance(s, dict) and any(k != "unrecorded"
                                        for k in (s.get("by_support_kind") or {}))
            for v in profs.values() if isinstance(v, dict) for s in v.values())
        no_mix = [f"{n}/{side}" for n, v in profs.items() if isinstance(v, dict)
                  for side, s in v.items() if isinstance(s, dict)
                  and not isinstance(s.get("by_support_kind"), dict)]
        if sk_recorded and no_mix:
            fails.append(f"axis strength: support_kind is recorded but {len(no_mix)} "
                         f"side profile(s) carry no by_support_kind mix (A3: the synthesis "
                         f"judge weighs the mix — '3 own-experiments + 12 "
                         f"position-assertions', never '15 papers'): {no_mix[:8]}")
        elif not sk_recorded:
            notes.append("axis strength: no support_kind recorded in any side profile — "
                         "legacy rows (mix not required)")

    # 11b. STRENGTH-NOTE convention — a data row carrying support_kind must also carry
    # a non-empty strength_note (always-written, like because/unless); rows with neither
    # field are legacy and pass untouched
    sk_bad = []
    for p in sorted(glob.glob(f"{report_dir}/data/*.jsonl")):
        for ln in open(p, errors="replace"):
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
                assert isinstance(r, dict)
            except Exception:
                continue
            basis = r.get("basis") if isinstance(r.get("basis"), dict) else {}
            sk = r.get("support_kind") or basis.get("support_kind")
            if not (isinstance(sk, str) and sk.strip()):
                continue
            note = r.get("strength_note") or basis.get("strength_note")
            if not (isinstance(note, str) and note.strip()):
                sk_bad.append(f"{os.path.basename(p)}:"
                              f"{r.get('corpusId', r.get('corpus_id', '?'))}")
    if sk_bad:
        fails.append(f"strength_note missing: {len(sk_bad)} shipped row(s) carry "
                     f"support_kind but an empty/absent strength_note — the nuance carrier "
                     f"is always written when support_kind is (always-written convention; trivially short when "
                     f"there is little to say): {sk_bad[:8]}")

    # 12. PLACEHOLDER SIDECAR — an all-zero *mix* block is a placeholder, not a measurement
    # (receipt: a shipped fit_mix was all-zero — the field existed, the counting never ran)
    ph = []
    for p in sorted(glob.glob(f"{report_dir}/data/*.json")):
        try:
            d = json.load(open(p))
        except Exception:
            continue    # unparseable data files are already loudly failed by check 4

        def _scan(x, path=""):
            if isinstance(x, dict):
                for k, v in x.items():
                    kp = f"{path}.{k}" if path else str(k)
                    if "mix" in str(k).lower() and isinstance(v, (dict, list)):
                        nl = _num_leaves(v)
                        if len(nl) >= 2 and all(n == 0 for n in nl):
                            ph.append(f"{os.path.basename(p)}: {kp} "
                                      f"({len(nl)} fields, all zero)")
                            continue
                    _scan(v, kp)
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    _scan(v, f"{path}[{i}]")
        _scan(d)
    if ph:
        fails.append(f"placeholder sidecar: {len(ph)} all-zero *mix* block(s) — compute "
                     f"the mix or drop the field, never ship a placeholder: {ph[:6]}")

    # 13. CLOSING-REBUILD CARRIED (round self-account) — new rounds only by construction: fires when
    # a round-manifest exists (a manifest-less new round already fails check 5)
    mpath = next((p for p in ([f"{run_dir}/round-manifest.json"] if run_dir else [])
                  + [f"{os.path.dirname(os.path.abspath(report_dir))}/round-manifest.json"]
                  if os.path.isfile(p)), None)
    if mpath:
        manifest = None
        try:
            manifest = json.load(open(mpath))
        except Exception as exc:
            fails.append(f"closing-rebuild: {mpath} unparseable ({exc})")
        if isinstance(manifest, dict):
            cr = manifest.get("closing_rebuild")
            need = ("regression_gate_count", "residual_unverified_spans")
            if (isinstance(cr, dict) and all(
                    isinstance(cr.get(k), int) and not isinstance(cr.get(k), bool)
                    and cr.get(k) >= 0 for k in need)):
                notes.append(f"closing_rebuild carried: regression_gate_count="
                             f"{cr['regression_gate_count']}, residual_unverified_spans="
                             f"{cr['residual_unverified_spans']} ({mpath})")
            else:
                fails.append(f"closing_rebuild absent/malformed in {mpath} — the round "
                             f"close must CARRY the closing rebuild's gate numbers as "
                             f"closing_rebuild {{regression_gate_count: int, "
                             f"residual_unverified_spans: int}} (vault.py rebuild prints "
                             f"both; receipt: a closing-rebuild regression gate fired "
                             f"unreported — the close must never silently absorb it)")
    else:
        notes.append("closing-rebuild: no round-manifest found — unchecked here "
                     "(check 5 already fails a manifest-less round on cost_actual)")

    # 14. CONSOLIDATION-COMPLETENESS — a page claiming to REPLACE prior reports carries
    # their still-standing content or DECLARES the narrowing (measured: a consolidation
    # dropped a disagreement-axes set, a product table and the full catalog into
    # superseded-only homes with no declaration). Fires only when superseded/ pages ship.
    sup_pages = sorted(glob.glob(f"{report_dir}/superseded/*.html")
                       + glob.glob(f"{report_dir}/superseded/*.md"))
    if sup_pages:
        def _h2s(text):
            hs = [re.sub(r"<[^>]+>", " ", m) for m in
                  re.findall(r"(?is)<h2[^>]*>(.*?)</h2>", text)]
            hs += re.findall(r"(?m)^##\s+([^\n]+)", text)
            out = set()
            for h in hs:
                c = _canon(re.sub(r"^\s*\d+\s*[·.:-]\s*", "", h))  # strip "5 ·" numbering
                if c and not any(b in c for b in (
                        "changelog", "package", "reference", "footer", "overview",
                        "correction", "what s new")):
                    out.add(c)
            return out
        standing_raw = " ".join(open(p, errors="replace").read() for p in pages
                                if "/superseded/" not in p.replace(os.sep, "/"))
        standing_h2 = _h2s(standing_raw)
        standing_canon = _canon(re.sub(r"<[^>]+>", " ", standing_raw))
        # the narrowing declaration must live NEAR the replaces-claim (changelog region) —
        # a quoted paper saying "drops to a threshold" must not immunize the page (measured)
        rep = re.search(r"(?i)replaces?\b", standing_raw)
        decl_zone = standing_raw[max(0, rep.start() - 1500):rep.start() + 3000] if rep \
            else standing_raw[:5000]
        narrowed = re.search(r"(?i)not carried|narrow(?:ed|ing)|does not carry|carried only"
                             r"|-focused report|left in the superseded", decl_zone)
        lost = []
        for sp in sup_pages:
            for h in _h2s(open(sp, errors="replace").read()):
                covered = any(h in s or s in h for s in standing_h2) or h in standing_canon
                if not covered:
                    lost.append(f"{os.path.basename(sp)}: '{h[:60]}'")
        if lost and not narrowed:
            fails.append(f"consolidation-completeness: {len(lost)} section(s) of the "
                         f"superseded pages have no home in the standing page and no "
                         f"declared narrowing — a page claiming to REPLACE prior reports "
                         f"carries their still-standing content or says what it dropped: "
                         f"{lost[:6]}")
        elif lost:
            notes.append(f"consolidation-completeness: {len(lost)} superseded section(s) "
                         f"not carried, but the page DECLARES its narrowing — listed, "
                         f"not silent: {lost[:4]}")
        else:
            notes.append("consolidation-completeness: all superseded sections covered")
    return fails, notes


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    run = args[args.index("--run") + 1] if "--run" in args else None
    mn = int(args[args.index("--min") + 1]) if "--min" in args else 10
    q = int(args[args.index("--questions") + 1]) if "--questions" in args else 4
    sf = int(args[args.index("--span-floor") + 1]) if "--span-floor" in args else 1
    fails, notes = gate(args[0], run, mn, q, span_floor=sf)
    for n in notes:
        print("  ·", n)
    if fails:
        print("REPORT GATE: FAIL")
        for f in fails:
            print("  ✗", f)
        sys.exit(1)
    print("REPORT GATE: PASS")
