"""vault.py — [T] build and grow a corpus thread's VAULT (see references/vault.md).

The growth model this enforces (the vault's whole integrity story):
  canonical rounds/<id>/ are APPEND-ONLY (folded verbatim, never edited);
  caches merge append-only (fetch-once; existing files win);
  view/union.jsonl + vault.json + vault.db are DERIVED — never hand-edited, always rebuilt here.
  vault.db is a DISPOSABLE sqlite index (query convenience only; NEVER canonical — delete and
  rebuild anytime; corruption remedy is delete+rebuild). See _build_db.
Rebuild is deterministic: same rounds in, same view out — a round runs it as its CLOSING
contract step; there is no human maintainer in the loop.

Usage:
  python vault.py init <workspace> --from <run_dir> [--id <round_id>]
      create <workspace>/vault/ with <run_dir> folded in as the founding round.
  python vault.py rebuild <workspace>
      fold any NEW <workspace>/round-*/ dirs (not yet in vault.json's registry) into
      vault/rounds/, merge their caches, and re-derive view/union.jsonl + vault.json
      + the vault.db EVIDENCE index (pointer ladder + regression/staleness gates run
      here, at the output boundary — see the evidence-layer block below).
  python vault.py where <workspace> <text-fragment>
      provenance-walk entry point: evidence rows whose quote/claim carries the fragment
      (round · kind · ladder rung · source file · cached text) — one query, no hand grep.
  python vault.py anchor <workspace-or-run-dir> <ids-file> [--label <label>]
      recall of a KNOWN-GOOD id list vs the store (folded here from knowledge.py per the
      primitive-work ruling; ids-file = JSON list, jsonl with corpusId, or one id per line).

Round discovery is by REGISTRY, not by name or mtime: a workspace round dir is new iff its
realpath is not recorded as a source in vault.json. New rounds are prepended (newest first =
column order and metadata precedence in the union view).
INVARIANT: vault.json rounds[] is NEWEST-FIRST — dispute-resolution and obs precedence both
ride on it (a legacy oldest-first registry produced bogus resolution marks until reordered).
"""
from __future__ import annotations
import glob, json, os, re, shutil, sqlite3, sys
from collections import Counter

FTS_SIZE_CAP = 2_000_000  # cache/fulltext-cache text files >= this are skipped by cache_fts

POS = ("in", "relevant")
# a round's canonical record is its WHOLE dir, verbatim — no filename enumeration (an
# earlier enum-based fold silently dropped rounds' living-axes docs and view deltas).
# Excluded: caches (merged separately into vault/cache/), PDFs, files > SIZE_CAP.
CACHE_DIRS = ("fulltext-cache", "s2-cache")
SIZE_CAP = 5_000_000
OBS_SOURCES = ("observations.jsonl", "observations-v1.jsonl", "view-delta.jsonl")


def _jl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def _fold_round(vault, rid, src):
    """Copy a round's canonical record VERBATIM into vault/rounds/<rid>/ (append-only:
    refuses to overwrite an existing round id)."""
    rdir = f"{vault}/rounds/{rid}"
    if os.path.isdir(rdir):
        raise SystemExit(f"rounds/{rid} already exists — canonical records are append-only "
                         f"(pick a new id; never rewrite a prior round)")
    os.makedirs(rdir)
    copied = []
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in CACHE_DIRS and not d.startswith(".")]
        rel = os.path.relpath(base, src)
        for f in files:
            p = os.path.join(base, f)
            if f.endswith(".pdf") or f.startswith(".") or os.path.getsize(p) > SIZE_CAP:
                continue
            dst = os.path.join(rdir, rel, f) if rel != "." else os.path.join(rdir, f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(p, dst)
            copied.append(os.path.relpath(dst, rdir))
    # caches merge append-only: existing vault copy wins (fetch-once, first capture kept)
    for cache in CACHE_DIRS:
        sdir = f"{src}/{cache}"
        if os.path.isdir(sdir):
            cdir = f"{vault}/cache/{cache}"
            os.makedirs(cdir, exist_ok=True)
            for f in os.listdir(sdir):
                if not os.path.exists(f"{cdir}/{f}"):
                    shutil.copy(f"{sdir}/{f}", f"{cdir}/{f}")
    as_of = None
    mp = f"{src}/round-manifest.json"
    if os.path.isfile(mp):
        try:
            as_of = json.load(open(mp)).get("as_of")
        except Exception:
            pass
    return {"id": rid, "source": os.path.realpath(src), "as_of": as_of,
            "judged": 0, "files": copied}


def _derive_aliases(obs_by_round):
    """Thread-side duplicate-id detection: same normalized title under 2+ corpusIds —
    mechanical and auditable; the vault needs no external id knowledge."""
    tid = {}
    for obs in obs_by_round.values():
        for cid, r in obs.items():
            t = re.sub(r"[^a-z0-9]", "", (r.get("title") or "").lower())
            if t:
                tid.setdefault(t, set()).add(cid)
    alias = {}
    for t, ids in tid.items():
        if len(ids) > 1:
            keep = min(ids)
            for c in ids:
                if c != keep:
                    alias[c] = keep
    return alias


# ------------------------------------------------------------- evidence layer
# (S-C build ruling 2026-07-27; design = evidence-layer-design.md, calibration = the
# sb-index-proto measurement.) The cross-round evidence INDEX is a DERIVED vault.db table:
# one row per claim-instance from every round's extract/*.jsonl + extractions.jsonl,
# rebuilt WHOLE on every rebuild (append-only facts; never hand-edited). Ingest is
# SCHEMA-TOLERANT — extraction schemas vary by round/thread; records that don't parse are
# COUNTED and reported, never fatal — and legacy records (no warrant fields) enter with
# fit=legacy-unwarranted. The POINTER is computed HERE, never LLM-emitted: a leniency
# ladder grades every verbatim span against the cached source text at rebuild time
#   exact → normalized (whitespace/unicode/ligature/hyphenation) → per-segment for
#   ellipsis composites (row rung = WORST segment) → fuzzy ≥ 0.90 (SOFT flag: measured,
#   below 0.90 the fail class blends into genuine paraphrase) → fail (grounding gate);
#   no_cache stays a SEPARATE rung — conflating it with fail tripled apparent staleness.
# Two gates ride the rebuild (gates-at-output-boundary doctrine; extraction stays BLIND —
# no packet-feeding of prior evidence):
#   REGRESSION — a later round's EMPTY record where an earlier round holds a substantive
#   same-or-deeper-tier record (r8-knew-less) → linked in gate_regression + 'regression'
#   flag on the later row; NEVER overwritten.
#   UNVERIFIED — a span that verifies against no reachable cache text → 'unverified' flag
#   ('stale' is RESERVED for source-change invalidation events — a distinct, ratified event kind)
#   (source change re-verify is mechanical: every rebuild re-runs the ladder, zero LLM).

FUZZY_BAR = 0.90       # calibrated: verified = exact/normalized · soft-flag ≥ 0.90 · fail below
_Q_KEYS = ("quote", "verbatim", "evidence_quote", "evidence_span", "finding_verbatim",
           "evidence", "span")
_C_KEYS = ("claim", "one_line_claim", "key_finding", "main_finding", "finding", "claim_text")
_KIND_ALIAS = {"coverage_est": "coverage", "strategy_repair": "repair",
               "failure_modes": "failure_mode", "positions": "stance"}
_LIST_STR_KINDS = ("failure_modes",)      # lists of bare strings that are claims, not metadata
_SKIP_EXTRACT_PREFIX = ("merged", "digest")   # round-internal derived copies of ex-* shards
_SLOT_META = ("addressed", "confidence", "fit", "because", "unless", "judged_by",
              "scope_flag", "lens", "polarity", "claim_type")
_DEPTH_SQL = ("CASE lower(coalesce({c},'')) WHEN 'fulltext' THEN 3 WHEN 'snippet' THEN 2 "
              "WHEN 'abstract' THEN 1 ELSE 0 END")
_UNI = str.maketrans({"‘": "'", "’": "'", "‚": "'", "“": '"',
                      "”": '"', "–": "-", "—": "-", "−": "-",
                      "­": "", " ": " ", " ": " ", " ": " "})
_LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}


def _norm_cid(v):
    """corpusId normalization over the 3 measured dialects: numeric string / raw int (both
    → canonical decimal string, whitespace + leading zeros killed) · web:Owner--Repo slugs
    (and anything else) verbatim."""
    if v is None:
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d+", s):
        return str(int(s))
    return s or None


def _norm_text(s):
    """Normalized-match text: unicode quotes/dashes/ligatures, whitespace collapse, ellipsis
    → '...' (the same matcher shape the run6 flow-through audit used)."""
    s = s.translate(_UNI)
    for k, v in _LIG.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s.replace("…", "...")).strip()


def _fuzzy_hit(nq, nd, thresh=FUZZY_BAR):
    """Sliding-window token-multiset overlap on normalized lowercased text — a cheap edit-
    distance proxy; honest at >= 0.90, increasingly generous below (measured)."""
    qt, dt = nq.lower().split(), nd.lower().split()
    w = len(qt)
    if w == 0 or len(dt) < w:
        return False
    need, window = Counter(qt), Counter(dt[:w])
    matched = sum(min(window[t], c) for t, c in need.items())
    goal = thresh * w
    if matched >= goal:
        return True
    for i in range(w, len(dt)):
        out_t, in_t = dt[i - w], dt[i]
        if out_t == in_t:
            continue
        if window[out_t] <= need.get(out_t, 0):
            matched -= 1
        window[out_t] -= 1
        window[in_t] += 1
        if window[in_t] <= need.get(in_t, 0):
            matched += 1
        if matched >= goal:
            return True
    return False


def _ladder(quote, raw, nds):
    """One quote vs one cache text → rung or None (fail vs THIS text). nds = (normalized,
    normalized-dehyphenated) precomputed once per document. Ellipsis composites grade
    PER-SEGMENT (>= 20-char segments); the row's rung is the WORST segment rung — partial
    verification stays visible instead of collapsing into an opaque fail."""
    if quote in raw:
        return "exact"
    nq = _norm_text(quote)
    nd, nd2 = nds
    if nq and (nq in nd or nq in nd2):
        return "normalized"
    if "..." in nq:
        segs = [s.strip(" .;,") for s in nq.split("...")]
        segs = [s for s in segs if len(s) >= 20]
        if segs:
            worst = "normalized"
            for s in segs:
                if s in nd or s in nd2:
                    continue
                if _fuzzy_hit(s, nd):
                    worst = "fuzzy"
                else:
                    return None
            return worst
    return "fuzzy" if _fuzzy_hit(nq, nd) else None


def _kind(k):
    """Claim-kind join key from a field name: strip question-slot prefixes (q1_stopping →
    stopping) + alias table, so the regression gate can compare kinds ACROSS round schemas."""
    k2 = re.sub(r"^q\d+_", "", k)
    return _KIND_ALIAS.get(k, _KIND_ALIAS.get(k2, k2))


def _slot_claim(d):
    """Best-effort claim text from a slot dict: join non-quote, non-meta scalar/str-list
    values (schema-tolerant — never guesses field semantics beyond quote-vs-not)."""
    parts = []
    for k, v in d.items():
        if k in _Q_KEYS or k in _SLOT_META:
            continue
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            parts.append(str(v))
        elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            parts.append(", ".join(x for x in v if x.strip()))
    return "; ".join(p for p in parts if p) or None


def _slot_quote(d):
    return next((d[k].strip() for k in _Q_KEYS
                 if isinstance(d.get(k), str) and d[k].strip()), None)


def _explode(rec, basis):
    """Record → claim tuples (kind, claim_type, claim, quote, polarity). Absence claims are
    FIRST-CLASS rows (addressed:false / null q-slots → claim+quote NULL, polarity=absent) —
    the regression gate needs them; absence is a claim, never a silent drop."""
    out = []
    claim = next((rec[k].strip() for k in _C_KEYS
                  if isinstance(rec.get(k), str) and rec[k].strip()), None)
    quote = _slot_quote(rec) or _slot_quote(basis)
    if claim or quote:
        ctype = rec.get("claim_type")
        out.append((ctype or "finding", ctype, claim, quote,
                    rec.get("polarity") or "present"))
    for k, v in rec.items():
        if isinstance(v, dict) and k != "basis":
            if "addressed" in v and not v["addressed"]:
                out.append((_kind(k), None, None, None, "absent"))
                continue
            if "addressed" not in v and not any(qk in v for qk in _Q_KEYS):
                continue                       # metadata dict, not a claim slot
            out.append((_kind(k), None, _slot_claim(v), _slot_quote(v), "present"))
        elif v is None and re.match(r"q\d+_", k):
            out.append((_kind(k), None, None, None, "absent"))
        elif isinstance(v, list) and v:
            if all(isinstance(e, dict) for e in v):
                for e in v:
                    sc, sq = _slot_claim(e), _slot_quote(e)
                    if sc or sq:
                        out.append((_kind(k), None, sc, sq, "present"))
            elif k in _LIST_STR_KINDS and all(isinstance(e, str) for e in v):
                for e in v:
                    if e.strip():
                        out.append((_kind(k), None, e.strip(), None, "present"))
    return out


def _build_evidence(cur, vault, rounds):
    """Ingest + ladder + gates (see the evidence-layer block comment). Called ONLY by
    _build_db inside its single transaction; returns the stats dict for layers."""
    for t in ("evidence", "gate_regression"):
        cur.execute(f"DROP TABLE IF EXISTS {t}")
    cur.execute("""CREATE TABLE evidence (
        id INTEGER PRIMARY KEY, corpusId TEXT, corpusId_raw TEXT, round TEXT,
        round_order INTEGER, source_file TEXT, claim_kind TEXT, claim_type TEXT,
        polarity TEXT, claim_text TEXT, quote TEXT, text_source TEXT, lens TEXT,
        fit TEXT, because TEXT, unless TEXT, scope_flag TEXT, confidence TEXT,
        judged_by TEXT, ladder_rung TEXT, ladder_target TEXT, flags TEXT, raw_json TEXT)""")
    cur.execute("CREATE INDEX idx_ev_cid ON evidence(corpusId)")
    cur.execute("CREATE INDEX idx_ev_join ON evidence(corpusId, claim_kind, round_order)")
    # registry is NEWEST-FIRST → round_order counts up from the oldest round = 1
    order = {r["id"]: len(rounds) - i for i, r in enumerate(rounds)}
    stats, rows, seen = Counter(), [], set()
    for r in rounds:
        rid = r["id"]
        rdir = f"{vault}/rounds/{rid}"
        files = [p for p in ([f"{rdir}/extractions.jsonl"]
                             + sorted(glob.glob(f"{rdir}/extract/**/*.jsonl", recursive=True)))
                 if os.path.isfile(p)
                 and not os.path.basename(p).startswith(_SKIP_EXTRACT_PREFIX)]
        for path in files:
            sf = os.path.relpath(path, vault)
            stats["files"] += 1
            for line in open(path, errors="replace"):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    assert isinstance(rec, dict)
                except Exception:
                    stats["bad_json_lines"] += 1
                    continue
                cid_raw = rec.get("corpusId", rec.get("corpus_id", rec.get("paperId")))
                cid = _norm_cid(cid_raw)
                if not cid:
                    stats["no_id_records"] += 1
                    continue
                stats["records"] += 1
                basis = rec.get("basis") if isinstance(rec.get("basis"), dict) else {}
                ts = (rec.get("text_source") or rec.get("evidence_depth")
                      or rec.get("source_tier") or basis.get("source") or basis.get("tier"))
                conf = rec.get("confidence")
                for kind, ctype, claim, quote, pol in _explode(rec, basis):
                    key = (rid, cid, kind, claim or "", quote or "")
                    if key in seen:            # merged.jsonl / shard-copy duplicates
                        stats["dup_rows"] += 1
                        continue
                    seen.add(key)
                    rows.append((cid, str(cid_raw), rid, order.get(rid, 0), sf, kind, ctype,
                                 pol, claim, quote, ts, rec.get("lens"),
                                 rec.get("fit") or "legacy-unwarranted", rec.get("because"),
                                 rec.get("unless"), rec.get("scope_flag"),
                                 None if conf is None else str(conf),
                                 rec.get("judged_by") or rec.get("extracted_by"),
                                 json.dumps(rec, ensure_ascii=False)))
    cur.executemany(
        "INSERT INTO evidence (corpusId, corpusId_raw, round, round_order, source_file,"
        " claim_kind, claim_type, polarity, claim_text, quote, text_source, lens, fit,"
        " because, unless, scope_flag, confidence, judged_by, raw_json)"
        " VALUES (" + ",".join("?" * 19) + ")", rows)
    # ---- pointer ladder: fulltext cache first, stored abstract as fallback (never conflated)
    ab_index = {}
    s2dir = f"{vault}/cache/s2-cache"
    if os.path.isdir(s2dir):
        for f in os.listdir(s2dir):
            m = re.match(r"paper-(\d+)[_.]", f)
            if m and f.endswith(".json"):
                ab_index.setdefault(m.group(1), []).append(f"{s2dir}/{f}")

    def _abstract(cid):
        for p in ab_index.get(cid, []):
            try:
                a = json.load(open(p)).get("abstract")
            except Exception:
                continue
            if a and a.strip():
                return a
        return None

    by_cid = {}
    for rowid, cid, quote in cur.execute("SELECT id, corpusId, quote FROM evidence"):
        by_cid.setdefault(cid, []).append((rowid, quote))
    updates = []
    for cid, items in sorted(by_cid.items()):
        ftp = f"{vault}/cache/fulltext-cache/{cid}.md"
        raw_ft = nds_ft = None
        if os.path.isfile(ftp):
            try:
                raw_ft = open(ftp, encoding="utf-8", errors="replace").read()
                nds_ft = (_norm_text(raw_ft), _norm_text(re.sub(r"-\n", "", raw_ft)))
            except OSError:
                raw_ft = None
        raw_abs, nds_abs, abs_loaded = None, None, False
        for rowid, quote in items:
            if quote is None:
                updates.append(("no_quote", None, None, rowid))
                continue
            rung = target = None
            if raw_ft is not None:
                rung = _ladder(quote, raw_ft, nds_ft)
                if rung:
                    target = "fulltext"
            if rung is None:
                if not abs_loaded:
                    raw_abs = _abstract(cid)
                    nds_abs = (_norm_text(raw_abs), _norm_text(raw_abs)) if raw_abs else None
                    abs_loaded = True
                if raw_abs:
                    r2 = _ladder(quote, raw_abs, nds_abs)
                    if r2:
                        rung, target = r2, "abstract"
            if rung is None:
                if raw_ft is None and not raw_abs:
                    rung, target = "no_cache", "none"
                else:
                    rung, target = "fail", ("fulltext" if raw_ft is not None else "abstract")
            flag = {"fail": "unverified", "fuzzy": "soft-pointer"}.get(rung)
            updates.append((rung, target, flag, rowid))
    cur.executemany(
        "UPDATE evidence SET ladder_rung=?, ladder_target=?, flags=? WHERE id=?", updates)
    # ---- regression gate: link + flag, never overwrite
    dep_e = _DEPTH_SQL.format(c="earlier.text_source")
    dep_l = _DEPTH_SQL.format(c="later.text_source")
    cur.execute(f"""CREATE TABLE gate_regression AS
        SELECT later.corpusId, later.claim_kind,
               earlier.round AS earlier_round, earlier.text_source AS earlier_text_source,
               substr(earlier.claim_text, 1, 160) AS earlier_claim,
               later.round AS later_round, later.text_source AS later_text_source,
               later.source_file AS later_file,
               earlier.id AS earlier_id, later.id AS later_id
        FROM evidence later
        JOIN evidence earlier
          ON  earlier.corpusId    = later.corpusId
          AND earlier.claim_kind  = later.claim_kind
          AND earlier.round_order < later.round_order
        WHERE later.claim_text IS NULL AND later.quote IS NULL
          AND earlier.claim_text IS NOT NULL
          AND {dep_e} >= {dep_l}""")
    cur.execute("UPDATE evidence SET flags = coalesce(flags || ',', '') || 'regression'"
                " WHERE id IN (SELECT later_id FROM gate_regression)")
    ladder = dict(cur.execute("SELECT ladder_rung, COUNT(*) FROM evidence"
                              " WHERE quote IS NOT NULL GROUP BY 1"))
    reg_pairs = cur.execute("SELECT COUNT(DISTINCT corpusId || '|' || claim_kind)"
                            " FROM gate_regression").fetchone()[0]
    reg_papers = cur.execute("SELECT COUNT(DISTINCT corpusId) FROM gate_regression").fetchone()[0]
    return {"rows": len(rows), "quoted": sum(1 for r in rows if r[9]),
            "records": stats["records"], "files": stats["files"],
            "skipped": {"bad_json_lines": stats["bad_json_lines"],
                        "no_id_records": stats["no_id_records"],
                        "dup_rows": stats["dup_rows"]},
            "ladder": ladder, "unverified": ladder.get("fail", 0),
            "regression": {"pairs": reg_pairs, "papers": reg_papers}}


def _build_db(vault, rows, rounds):
    """Materialize <vault>/vault.db — a DISPOSABLE sqlite DERIVED INDEX over the union view
    (+ questions, trust-upgrades, an FTS5 index of the fulltext cache, and the EVIDENCE
    table + gate_regression via _build_evidence) for ad-hoc queries.

    NEVER CANONICAL. The source of truth is rounds/ + view/union.jsonl; vault.db is dropped and
    rebuilt WHOLE on every _derive, so it is always reconstructable and the corruption remedy is
    simply delete+rebuild. A meta row (key='disposable') records this inside the db itself.
    Called only by _derive (the sole writer of derived layers). stdlib sqlite3 only; one txn."""
    dbp = f"{vault}/vault.db"
    con = sqlite3.connect(dbp, isolation_level=None)  # explicit BEGIN/COMMIT = one transaction
    try:
        cur = con.cursor()
        cur.execute("BEGIN")
        for t in ("rows", "questions", "trust_upgrades", "meta"):
            cur.execute(f"DROP TABLE IF EXISTS {t}")
        cur.execute("DROP TABLE IF EXISTS cache_fts")
        cur.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        cur.executemany("INSERT INTO meta VALUES (?,?)", [
            ("disposable", "delete and rebuild anytime"),
            ("note", "DERIVED index, NOT canonical. Source of truth = rounds/ + view/union.jsonl. "
                     "Rebuilt whole on every `vault.py rebuild`; corruption remedy = delete+rebuild.")])
        cur.execute("""CREATE TABLE rows (
            corpusId TEXT PRIMARY KEY, title TEXT, year INTEGER, agreement TEXT, trust TEXT,
            n_rounds_judged INTEGER, resolved_tier TEXT, resolved_by TEXT,
            primary_family TEXT, tiers_json TEXT)""")
        cur.executemany("INSERT OR REPLACE INTO rows VALUES (?,?,?,?,?,?,?,?,?,?)", [
            (r["corpusId"], r.get("title"), r.get("year"), r.get("agreement"), r.get("trust"),
             r.get("n_rounds_judged"), (r.get("resolved_latest") or {}).get("tier"),
             (r.get("resolved_latest") or {}).get("by"), r.get("primary_family_latest"),
             json.dumps(r.get("tiers_by_round"), ensure_ascii=False)) for r in rows])
        # questions from QUESTIONS.log — skip any unparseable line ("if parseable")
        cur.execute("CREATE TABLE questions (q TEXT, asked_by TEXT, status TEXT, answer TEXT)")
        qp = f"{vault}/QUESTIONS.log"
        if os.path.isfile(qp):
            qrows = []
            for line in open(qp):
                if not line.strip():
                    continue
                try:
                    x = json.loads(line)
                except Exception:
                    continue
                qrows.append((x.get("q"), x.get("asked_by"), x.get("status"), x.get("answer")))
            cur.executemany("INSERT INTO questions VALUES (?,?,?,?)", qrows)
        # trust_upgrades from rounds/*/trust-upgrades.jsonl — round_id from the owning round dir
        cur.execute("""CREATE TABLE trust_upgrades (
            round_id TEXT, corpusId TEXT, claim TEXT, from_mark TEXT, to_mark TEXT)""")
        turows = []
        for r in rounds:
            tp = f"{vault}/rounds/{r['id']}/trust-upgrades.jsonl"
            if os.path.isfile(tp):
                for x in _jl(tp):
                    cid = x.get("corpusId")
                    turows.append((r["id"], str(cid) if cid is not None else None,
                                   x.get("claim"), x.get("from_mark"), x.get("to_mark")))
        cur.executemany("INSERT INTO trust_upgrades VALUES (?,?,?,?,?)", turows)
        # FTS5 over cache/fulltext-cache: text files < 2MB only (skip pdf + undecodable binaries)
        cur.execute("CREATE VIRTUAL TABLE cache_fts USING fts5(corpusId, body)")
        cdir = f"{vault}/cache/fulltext-cache"
        ftrows = []
        if os.path.isdir(cdir):
            for base, _dirs, files in os.walk(cdir):
                for fn in files:
                    p = os.path.join(base, fn)
                    if fn.endswith(".pdf") or os.path.getsize(p) >= FTS_SIZE_CAP:
                        continue
                    try:
                        body = open(p, encoding="utf-8").read()
                    except (UnicodeDecodeError, OSError):
                        continue  # binary / unreadable — skipped
                    ftrows.append((os.path.splitext(fn)[0], body))
        cur.executemany("INSERT INTO cache_fts (corpusId, body) VALUES (?,?)", ftrows)
        ev_stats = _build_evidence(cur, vault, rounds)
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return {"rows": len(rows), "questions_file": os.path.isfile(f"{vault}/QUESTIONS.log"),
            "fts_docs": len(ftrows), "trust_upgrades": len(turows), "evidence": ev_stats}


def _derive(vault, rounds):
    """Re-derive view/union.jsonl + layer stats from vault/rounds/* — the only writer of
    derived layers. Round order = registry order (newest first): column order + obs precedence."""
    tiers_by_round, obs_by_round = {}, {}
    for r in rounds:
        rdir = f"{vault}/rounds/{r['id']}"
        rel_p = f"{rdir}/standardized-relevance.jsonl"
        rel = {str(x["corpusId"]): x.get("tier") for x in _jl(rel_p)} if os.path.isfile(rel_p) else {}
        obs = {}
        for cand in OBS_SOURCES:
            if os.path.isfile(f"{rdir}/{cand}"):
                obs = {str(x["corpusId"]): x for x in _jl(f"{rdir}/{cand}")}
                break
        tiers_by_round[r["id"]], obs_by_round[r["id"]] = rel, obs
        r["judged"] = len(rel)
    alias = _derive_aliases(obs_by_round)
    A = lambda c: alias.get(c, c)
    tiers_by_round = {rid: {A(c): t for c, t in rel.items()} for rid, rel in tiers_by_round.items()}
    obs_by_round = {rid: {A(c): x for c, x in o.items()} for rid, o in obs_by_round.items()}
    all_ids = set()
    for rel in tiers_by_round.values():
        all_ids |= set(rel)
    order = list(tiers_by_round)  # registry order = newest first
    rows = []
    for cid in sorted(all_ids):
        tiers = {rid: tiers_by_round[rid][cid] for rid in tiers_by_round
                 if cid in tiers_by_round[rid]}
        judged = [t for t in tiers.values() if t]
        pos = [t in POS for t in judged]
        agreement = ("agreed-positive" if judged and all(pos) else
                     "agreed-negative" if judged and not any(pos) else
                     "DISPUTED" if judged else "unjudged")
        # dispute resolution overlay: the newest opinion RESOLVES iff the conflict already
        # existed among strictly OLDER rounds (a deliberate re-judge of a known dispute, per
        # the operating clause). A newest opinion that CREATES the conflict resolves nothing.
        # History is never erased: agreement stays DISPUTED; this is the thread's current call.
        resolved = None
        if agreement == "DISPUTED":
            seq = [(rid, tiers[rid]) for rid in order if rid in tiers and tiers[rid]]
            older = [t in POS for _, t in seq[1:]]
            if any(older) and not all(older):  # conflict predates the newest opinion
                resolved = {"tier": seq[0][1], "by": seq[0][0]}
        o = next((obs_by_round[r][cid] for r in obs_by_round if cid in obs_by_round[r]), {})
        rows.append({"corpusId": cid, "title": o.get("title"), "year": o.get("year"),
                     "tiers_by_round": tiers, "n_rounds_judged": len(judged),
                     "agreement": agreement, "resolved_latest": resolved,
                     "trust": (f"DISPUTED-resolved:{resolved['tier']}/{resolved['by']}"
                               if resolved else f"{agreement}/{len(judged)}x"),
                     "primary_family_latest": o.get("primary_family") or o.get("primary_family_latest")})
    os.makedirs(f"{vault}/view", exist_ok=True)
    with open(f"{vault}/view/union.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    layers = {"aliases": {"pairs": len(alias), "map": alias},
              "view": {"rows": len(rows),
                       "agreement": dict(Counter(r["agreement"] for r in rows)),
                       "judged_by_n_rounds": dict(sorted(Counter(
                           r["n_rounds_judged"] for r in rows).items()))}}
    for cache in ("fulltext-cache", "s2-cache"):
        cdir = f"{vault}/cache/{cache}"
        layers[cache] = {"files": len(os.listdir(cdir)) if os.path.isdir(cdir) else 0}
    # disposable sqlite derived index — materialized AFTER union.jsonl, from the same rows
    layers["db"] = _build_db(vault, rows, rounds)
    layers["evidence"] = layers["db"].pop("evidence")  # top-level layer: it has its own gates
    return layers


def rebuild(workspace, amend=None):
    """Prints its own BEFORE/AFTER delta (rows, agreement, 2x-layer) — every measured session
    hand-wrapped rebuild with exactly these snapshots; the tool now provides them."""
    vault = f"{workspace}/vault"
    vj = f"{vault}/vault.json"
    meta = json.load(open(vj)) if os.path.isfile(vj) else {"rounds": [], "layers": {}}
    before = (meta.get("layers", {}) or {}).get("view", {})
    if amend:
        # amendment semantics: ONLY the latest round may be re-folded (post-close fixes);
        # earlier rounds stay immutable (measured: a round's post-close report fixes left
        # its canonical copy stale, and append-only correctly refused a silent re-fold)
        if not meta["rounds"] or meta["rounds"][0]["id"] != amend:
            raise SystemExit(f"--amend {amend}: only the LATEST round "
                             f"({meta['rounds'][0]['id'] if meta['rounds'] else 'none'}) is amendable")
        shutil.rmtree(f"{vault}/rounds/{amend}", ignore_errors=True)
        meta["rounds"] = meta["rounds"][1:]
    # identity must survive a moved/copied workspace: match id, recorded path, OR the
    # recorded source's basename (a copied workspace re-folding its own rounds = 2x rows)
    known = ({r.get("source") for r in meta["rounds"]} | {r["id"] for r in meta["rounds"]}
             | {os.path.basename(r["source"]) for r in meta["rounds"] if r.get("source")})
    new = []
    for d in sorted(os.listdir(workspace), reverse=True):  # newest round number first
        p = f"{workspace}/{d}"
        # a closable round has at least a round-manifest; rows-less rounds (pure
        # consolidation/audit) still fold — their manifests + trust-upgrades are vault knowledge
        if (re.fullmatch(r"round-[\w.-]+", d) and os.path.isdir(p)
                and os.path.realpath(p) not in known and d not in known
                and (os.path.isfile(f"{p}/round-manifest.json")
                     or os.path.isfile(f"{p}/standardized-relevance.jsonl"))):
            new.append((d, p))
    for rid, src in new:
        # contract-as-code (minimal fields only): a round without charter provenance and an
        # as-of date cannot fold — measured: charter rulings that lived only in transcripts
        # were invisible to later fleets; the manifest is the durable carrier.
        mp = f"{src}/round-manifest.json"
        try:
            rm = json.load(open(mp))
        except Exception:
            raise SystemExit(f"{rid}: round-manifest.json missing/unreadable — the round "
                             f"contract requires it (charter provenance + as_of) before fold")
        if not rm.get("as_of") or not (rm.get("charter") or rm.get("charter_file")
                                       or rm.get("charter_inherited_from")):
            raise SystemExit(f"{rid}: round-manifest.json must carry 'as_of' and charter "
                             f"provenance ('charter', 'charter_file', or "
                             f"'charter_inherited_from' — inherited-verbatim-from-<round> "
                             f"or amendments listed)")
        meta["rounds"].insert(0, _fold_round(vault, rid, src))
        print(f"folded {rid} <- {src}")
    meta["layers"] = _derive(vault, meta["rounds"])
    json.dump(meta, open(vj, "w"), indent=1)
    after = meta["layers"]["view"]
    if before:
        d_rows = after["rows"] - before.get("rows", 0)
        b_agr, a_agr = before.get("agreement", {}), after.get("agreement", {})
        deltas = {k: a_agr.get(k, 0) - b_agr.get(k, 0) for k in set(a_agr) | set(b_agr)
                  if a_agr.get(k, 0) != b_agr.get(k, 0)}
        print(f"DELTA: rows {before.get('rows','?')}→{after['rows']} ({d_rows:+d}) · "
              f"agreement changes {deltas or 'none'}")
    ev = meta["layers"].get("evidence") or {}
    if ev.get("rows"):
        print(f"EVIDENCE: {ev['rows']} claim rows ({ev['quoted']} quoted) from "
              f"{ev['records']} records / {ev['files']} files · skipped {ev['skipped']} · "
              f"ladder {ev['ladder']}")
        reg = ev.get("regression") or {}
        if reg.get("pairs"):
            print(f"  ⚠ REGRESSION GATE FIRED: {reg['pairs']} (paper,kind) pairs on "
                  f"{reg['papers']} papers — a later round knew LESS than an existing "
                  f"deeper-tier record (linked in vault.db gate_regression + 'regression' "
                  f"flags; earlier rows kept, nothing overwritten)")
        if ev.get("unverified"):
            print(f"  ⚠ UNVERIFIED: {ev['unverified']} spans verify against NO reachable cache text "
                  f"('unverified' flag; 'stale' is reserved for source-change events; no_cache separate — "
                  f"never conflate reachability with failure)")
    return meta


def init(workspace, run_dir, rid="r1"):
    vault = f"{workspace}/vault"
    if os.path.isdir(f"{vault}/rounds"):
        raise SystemExit(f"{vault} already initialized — use rebuild")
    os.makedirs(vault, exist_ok=True)
    meta = {"rounds": [_fold_round(vault, rid, run_dir)], "layers": {}}
    meta["layers"] = _derive(vault, meta["rounds"])
    json.dump(meta, open(f"{vault}/vault.json", "w"), indent=1)
    open(f"{vault}/QUESTIONS.log", "a").close()
    with open(f"{vault}/VAULT-MANIFEST.template.md", "w") as f:
        f.write("# VAULT — <topic>\n<instantiate from references/vault.md template; "
                "counts live in vault.json, don't copy them into prose>\n")
    return meta


def verify(workspace):
    """Staleness/corruption check for the DERIVED layers (the vault analog of validate.py's
    collection.meta check): recompute the derivation in memory and diff against what's on
    disk; also compare each round's current row count against the registry's fold-time count.
    Exit non-zero on any drift — run before trusting the view after any manual surgery."""
    vault = f"{workspace}/vault"
    meta = json.load(open(f"{vault}/vault.json"))
    fails = []
    for r in meta["rounds"]:
        rp = f"{vault}/rounds/{r['id']}/standardized-relevance.jsonl"
        n = sum(1 for l in open(rp) if l.strip()) if os.path.isfile(rp) else 0
        if n != r.get("judged", 0):
            fails.append(f"round {r['id']}: rows now {n} != registry {r.get('judged')} (post-rebuild edit? use --amend)")
    # snapshot the on-disk union BEFORE recomputing (_derive is the writer); after the
    # recompute, diff old vs new. On drift this check REPORTS FAIL and leaves the vault
    # consistent (the fresh derivation) — stated behavior, not a silent mutation.
    up = f"{vault}/view/union.jsonl"
    before = {r["corpusId"]: r for r in (json.loads(l) for l in open(up))} if os.path.isfile(up) else {}
    # vault.db is a DISPOSABLE derived index: snapshot its row count BEFORE the recompute
    # (_build_db, called by _derive, rebuilds it fresh — so this compares the on-disk db as it
    # stood against the freshly derived union, then leaves the db consistent).
    dbp = f"{vault}/vault.db"
    db_before = None
    if os.path.isfile(dbp):
        try:
            dbc = sqlite3.connect(dbp)
            db_before = dbc.execute("SELECT count(*) FROM rows").fetchone()[0]
            dbc.close()
        except Exception:
            db_before = None  # unreadable/corrupt — treat as missing, rebuild refreshes it
    import copy
    _derive(vault, copy.deepcopy(meta["rounds"]))
    after = {r["corpusId"]: r for r in (json.loads(l) for l in open(up))}
    drift = [k for k in after if before.get(k) != after[k]] + [k for k in before if k not in after]
    if drift:
        fails.append(f"union was STALE: {len(drift)} rows differed from the sources "
                     f"(now refreshed by this check)")
    if db_before != len(after):
        fails.append(f"vault.db was STALE/missing: {db_before} rows != union {len(after)} "
                     f"(disposable index rebuilt by this check)")
    for f in fails:
        print("STALE:", f)
    print("VAULT VERIFY:", "FAIL (refreshed)" if fails else "OK",
          f"({len(meta['rounds'])} rounds, {len(after)} rows)")
    return 1 if fails else 0


def where(workspace, frag, limit=20):
    """Provenance-walk entry point (interrogation convention 1): rendered claim → evidence
    row → span → cached source, one LIKE query over the evidence index. A zero-hit result is
    'not found in <this index>', NEVER 'does not exist' — absence claims need the full walk."""
    dbp = f"{workspace}/vault/vault.db"
    if not os.path.isfile(dbp):
        raise SystemExit(f"{dbp} missing — run `vault.py rebuild {workspace}` first "
                         f"(the evidence index is derived, never hand-built)")
    con = sqlite3.connect(dbp)
    try:
        total = con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    except sqlite3.OperationalError:
        raise SystemExit("vault.db predates the evidence layer — rebuild to grow it")
    esc = frag.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    pat = f"%{esc}%"
    hits = con.execute(
        "SELECT corpusId, round, claim_kind, coalesce(ladder_rung,'?'),"
        " coalesce(ladder_target,''), coalesce(flags,''), source_file,"
        " substr(coalesce(claim_text,''),1,140), substr(coalesce(quote,''),1,140)"
        " FROM evidence WHERE quote LIKE ? ESCAPE '\\' OR claim_text LIKE ? ESCAPE '\\'"
        " ORDER BY round_order DESC LIMIT ?", (pat, pat, limit + 1)).fetchall()
    con.close()
    more = len(hits) > limit
    for cid, rnd, kind, rung, tgt, flags, sf, ct, qt in hits[:limit]:
        cache = f"{workspace}/vault/cache/fulltext-cache/{cid}.md"
        print(f"{cid} · {rnd} · {kind} · rung={rung}{'/' + tgt if tgt else ''}"
              + (f" · FLAGS={flags}" if flags else ""))
        if ct:
            print(f"  claim: {ct}")
        if qt:
            print(f"  quote: {qt}")
        print(f"  row source: {sf} · cached text: "
              f"{cache if os.path.isfile(cache) else '(no fulltext cache for this id)'}")
    n = len(hits[:limit])
    print(f"{n}{'+' if more else ''} hit(s) for {frag!r} over {total} evidence rows "
          f"(fields searched: claim_text + quote)"
          + ("" if n else " — NOT-FOUND-IN-THIS-SCOPE, not proof of absence"))
    return n


def anchor(ids, tiers, obs=None, edges=None, label=""):
    """Recall of a KNOWN-GOOD set (survey refs, expert list, enumerated canon) vs the store —
    OFFLINE (folded from knowledge.py per primitive-work ruling 3). Interpret with care: low
    recall→relevant is often deliberate exclusion, not a miss (check n_judged_out_of_scope).
    Only never_seen are candidate gaps → hand to Acquire. Membership consults ALL layers
    (tiers / observations / edges) or it lies about what was seen."""
    obs, edges = obs or {}, edges or {}
    ids = [str(i) for i in ids]
    seen = [i for i in ids if (i in tiers or i in obs or i in edges)]
    relevant = [i for i in seen if tiers.get(i) in POS]
    judged_out = [i for i in seen if tiers.get(i) in ("not-relevant", "out")]
    never_seen = [i for i in ids if i not in seen]
    n = len(ids) or 1
    return {"label": label, "n": len(ids),
            "recall_relevant": len(relevant) / n, "recall_seen": len(seen) / n,
            "n_relevant": len(relevant), "n_seen": len(seen),
            "n_judged_out_of_scope": len(judged_out),
            "n_never_seen": len(never_seen), "never_seen": never_seen}


def anchor_layers(path):
    """(tiers, obs, edges) membership layers for anchor() — from a WORKSPACE with a vault
    (tier = the thread's current call: resolved tier, else the newest round's) or, legacy,
    a run dir with the standard files (observations / standardized-relevance / edges-cache)."""
    vault = f"{path}/vault" if os.path.isdir(f"{path}/vault") else path
    up = f"{vault}/view/union.jsonl"
    if os.path.isfile(up):
        order = [r["id"] for r in json.load(open(f"{vault}/vault.json"))["rounds"]]
        tiers, obs = {}, {}
        for l in open(up):
            r = json.loads(l)
            cid = r["corpusId"]
            obs[cid] = r
            tbr = r.get("tiers_by_round") or {}
            tiers[cid] = ((r.get("resolved_latest") or {}).get("tier")
                          or next((tbr[rid] for rid in order if tbr.get(rid)), None))
        edges = {}
        s2dir = f"{vault}/cache/s2-cache"
        if os.path.isdir(s2dir):
            for f in os.listdir(s2dir):
                m = re.match(r"edges-(\d+)[_.]", f)
                if m:
                    edges[m.group(1)] = True
        return tiers, obs, edges
    tiers = {str(r["corpusId"]): r.get("tier")
             for r in map(json.loads, open(f"{path}/standardized-relevance.jsonl"))}
    op = f"{path}/observations.jsonl"
    obs = {str(r["corpusId"]): r for r in map(json.loads, open(op))} if os.path.isfile(op) else {}
    ep = f"{path}/edges-cache.json"
    edges = {str(k): v for k, v in json.load(open(ep)).items()} if os.path.isfile(ep) else {}
    return tiers, obs, edges


def _read_ids(path):
    """ids-file tolerance: JSON list (of ids or dicts) · jsonl with corpusId · one id/line."""
    text = open(path).read().strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x.get("corpusId")) if isinstance(x, dict) else str(x) for x in data]
    except json.JSONDecodeError:
        pass
    ids = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ids.append(str(r.get("corpusId")) if isinstance(r, dict) else str(r))
        except json.JSONDecodeError:
            ids.append(line)
    return ids


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "rebuild":
        amend = sys.argv[sys.argv.index("--amend") + 1] if "--amend" in sys.argv else None
        m = rebuild(sys.argv[2], amend=amend)
    elif cmd == "recall":
        # C3: union-recall — a round's positives vs the vault's agreed-positive union.
        # STANDARD REPORTED SIGNAL (receipt: known truth ~doubles per new enumerator; recall
        # vs the union is the honest, always-available denominator — with the union caveat:
        # the union GROWS, so this is recall vs currently-known, never vs the world).
        ws, rid = sys.argv[2], sys.argv[3]
        meta = json.load(open(f"{ws}/vault/vault.json"))
        union_pos = set(); mine = set()
        for l in open(f"{ws}/vault/view/union.jsonl"):
            r = json.loads(l)
            if r["agreement"] == "agreed-positive" or (r.get("resolved_latest") or {}).get("tier") in POS:
                union_pos.add(r["corpusId"])
                if (r["tiers_by_round"].get(rid) or "") in POS:
                    mine.add(r["corpusId"])
        print(f"{rid}: {len(mine)}/{len(union_pos)} = {len(mine)/max(len(union_pos),1):.1%} "
              f"of currently-known union positives (union grows with every enumerator — "
              f"this is recall vs KNOWN, not vs the world)")
        sys.exit(0)
    elif cmd == "verify":
        sys.exit(verify(sys.argv[2]))
    elif cmd == "where":
        if len(sys.argv) < 4 or not os.path.isdir(os.path.join(sys.argv[2], "vault")):
            print("usage: vault.py where <workspace> <text-fragment>   "
                  "(workspace = the dir containing vault/; searches claim_text + quote)")
            sys.exit(2)
        where(sys.argv[2], sys.argv[3])
        sys.exit(0)
    elif cmd == "anchor":
        label = (sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv
                 else os.path.basename(sys.argv[3]))
        print(json.dumps(anchor(_read_ids(sys.argv[3]), *anchor_layers(sys.argv[2]),
                                label=label), indent=1))
        sys.exit(0)
    elif cmd == "init":
        src = sys.argv[sys.argv.index("--from") + 1]
        rid = sys.argv[sys.argv.index("--id") + 1] if "--id" in sys.argv else "r1"
        m = init(sys.argv[2], src, rid)
    else:
        raise SystemExit(__doc__)
    print(json.dumps(m["layers"]["view"], indent=1))
    for r in m["rounds"]:
        print(f"  {r['id']}: {r['judged']} judged · as-of {r.get('as_of')}")
