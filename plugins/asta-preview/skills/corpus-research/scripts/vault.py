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
      vault/rounds/, merge their caches, and re-derive view/union.jsonl + vault.json.

Round discovery is by REGISTRY, not by name or mtime: a workspace round dir is new iff its
realpath is not recorded as a source in vault.json. New rounds are prepended (newest first =
column order and metadata precedence in the union view).
INVARIANT: vault.json rounds[] is NEWEST-FIRST — dispute-resolution and obs precedence both
ride on it (a legacy oldest-first registry produced bogus resolution marks until reordered).
"""
from __future__ import annotations
import json, os, re, shutil, sqlite3, sys
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


def _build_db(vault, rows, rounds):
    """Materialize <vault>/vault.db — a DISPOSABLE sqlite DERIVED INDEX over the union view
    (+ questions, trust-upgrades, and an FTS5 index of the fulltext cache) for ad-hoc queries.

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
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return {"rows": len(rows), "questions_file": os.path.isfile(f"{vault}/QUESTIONS.log"),
            "fts_docs": len(ftrows), "trust_upgrades": len(turows)}


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
    elif cmd == "init":
        src = sys.argv[sys.argv.index("--from") + 1]
        rid = sys.argv[sys.argv.index("--id") + 1] if "--id" in sys.argv else "r1"
        m = init(sys.argv[2], src, rid)
    else:
        raise SystemExit(__doc__)
    print(json.dumps(m["layers"]["view"], indent=1))
    for r in m["rounds"]:
        print(f"  {r['id']}: {r['judged']} judged · as-of {r.get('as_of')}")
