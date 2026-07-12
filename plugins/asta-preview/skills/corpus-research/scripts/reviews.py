"""reviews.py — [T] OpenReview review-register fetcher (a MODALITY: peer reviews of corpus
papers feed disagreement-axis CANDIDATE GENERATION, contested-claim evidence, and meta-review
anchors — see deliverables.md disagreement doctrine and coverage-playbook anchors).

Scope honesty: OpenReview-hosted venues only (ICLR, NeurIPS, etc.) — a STRATUM of the corpus,
never the population; regime language applies to any claim built on it.

Access (measured constraints, 2026-07-12):
  - Anonymous access is bot-challenged; a FREE registered account is the sanctioned path
    (ToS: the API exists for "search, and download"; identity/affiliation must be truthful).
  - Credentials: env OPENREVIEW_USERNAME/OPENREVIEW_PASSWORD, or ~/.config/openreview.env.
    NEVER logged, never cached in the run dir.
  - LOGIN is rate-limited (~3/window) — tokens are cached at ~/.cache/openreview-tokens.json
    (user-level cache, NOT the run dir: run dirs get folded into vaults) and reused (~6 days).
  - Requests paced ~1.5s, serialized — same discipline as s2.py.
  - Two APIs: v1 (pre-2024 venues; fuzzy title search WORKS) and v2 (2024+; search is
    unavailable server-side → resolution via a cached per-venue title index).
Measured reach (pilot: 15-paper corpus slice): 13/13 papers WITH obtainable reviews resolved
(~53 reviews + decisions); the 2 misses are STRUCTURAL — NeurIPS pre-2021 predates its move
to OpenReview (reviews don't exist there). State the boundary: ICLR ~2017+, NeurIPS 2021+.
Validated against a hand-verified slice: 8/8 reviewer quotes extracted from browser-saved
PDFs were found verbatim in API fetches across both API versions.

Usage:
  python reviews.py fetch <run_dir> --title "<paper title>" [--year YYYY] [--corpus-id N]
  python reviews.py batch <run_dir> <papers.jsonl>     # rows: {corpusId, title, year}
Outputs: <run>/review-cache/<forum>.json (raw notes, fetch-once) and appends normalized rows
to <run>/reviews.jsonl: {corpusId, title, forum, api, venue, decision, n_reviews,
reviews: [{signature, rating, text}], meta_review}.
"""
from __future__ import annotations
import json, os, re, sys, time

TOKENS = os.path.expanduser("~/.cache/openreview-tokens.json")
CREDS = os.path.expanduser("~/.config/openreview.env")
PACE = 1.5
_clients = {}


def _creds():
    u, p = os.environ.get("OPENREVIEW_USERNAME"), os.environ.get("OPENREVIEW_PASSWORD")
    if not (u and p) and os.path.exists(CREDS):
        for line in open(CREDS):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                if k == "OPENREVIEW_USERNAME": u = u or v
                if k == "OPENREVIEW_PASSWORD": p = p or v
    if not (u and p):
        raise SystemExit("no OpenReview credentials (env or ~/.config/openreview.env)")
    return u, p


def client(ver):
    if ver in _clients:
        return _clients[ver]
    import openreview
    base = "https://api.openreview.net" if ver == 1 else "https://api2.openreview.net"
    cls = openreview.Client if ver == 1 else openreview.api.OpenReviewClient
    toks = json.load(open(TOKENS)) if os.path.exists(TOKENS) else {}
    key = f"v{ver}"
    if toks.get(key, {}).get("exp", 0) > time.time() + 3600:
        c = cls(baseurl=base, token=toks[key]["token"])
    else:
        u, p = _creds()
        c = cls(baseurl=base, username=u, password=p)  # login is rate-limited: reuse tokens!
        toks[key] = {"token": c.token, "exp": time.time() + 6 * 24 * 3600}
        os.makedirs(os.path.dirname(TOKENS), exist_ok=True)
        json.dump(toks, open(TOKENS, "w"))
        os.chmod(TOKENS, 0o600)
    _clients[ver] = c
    return c


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _val(x):
    return x.get("value") if isinstance(x, dict) else x


def resolve_dblp(run, corpus_id=None, dblp_key=None):
    """Rung 0 — DETERMINISTIC, search-free: corpusId -> S2 externalIds.DBLP (conference key)
    -> DBLP record's ee = the OpenReview forum URL. Measured reach: ICLR conf-keys resolve
    exactly; NeurIPS ee points to papers.nips.cc (use the venue index instead); S2 sometimes
    carries the journals/corr key (arXiv version) — falls through to the next rung."""
    import urllib.request
    os.makedirs(f"{run}/review-cache", exist_ok=True)
    mp = f"{run}/review-cache/dblp-map.json"
    m = json.load(open(mp)) if os.path.exists(mp) else {}
    key = dblp_key
    if not key and corpus_id:
        if str(corpus_id) in m:
            key = m[str(corpus_id)]
        elif os.environ.get("S2_API_KEY"):
            time.sleep(PACE)
            try:
                req = urllib.request.Request(
                    f"https://api.semanticscholar.org/graph/v1/paper/CorpusId:{corpus_id}?fields=externalIds",
                    headers={"x-api-key": os.environ["S2_API_KEY"]})
                key = (json.load(urllib.request.urlopen(req, timeout=15)).get("externalIds") or {}).get("DBLP")
            except Exception:
                key = None
            m[str(corpus_id)] = key
            json.dump(m, open(mp, "w"))
    if not key or not key.startswith("conf/"):
        return None
    time.sleep(PACE)
    try:
        xml = urllib.request.urlopen(urllib.request.Request(
            f"https://dblp.org/rec/{key}.xml", headers={"User-Agent": "corpus-research"}), timeout=15).read().decode()
    except Exception:
        return None
    hits = re.findall(r"openreview\.net/forum\?id=([\w-]+)", xml)
    return hits[0] if hits else None


def resolve_v1(title):
    """Fuzzy search works on v1 (pre-2024 venues). Returns ALL title-matching forums, best
    match first — version multiplicity is real (the same paper can have submitted/rejected/
    workshop copies; the caller prefers the forum that carries official reviews)."""
    time.sleep(PACE)
    notes = client(1).search_notes(term=re.sub(r"[^\w\s]", " ", title)[:120],
                                   content="all", group="all", source="forum")
    n0 = _norm(title)
    exact, prefix = [], []
    for n in notes:
        nt = _norm(_val(n.content.get("title", "")))
        if nt == n0:
            exact.append(n.forum)
        elif nt[:60] == n0[:60]:
            prefix.append(n.forum)
    seen, out = set(), []
    for f in exact + prefix:
        if f not in seen:
            seen.add(f); out.append(f)
    return out


def venue_index(run, venueid):
    """v2 has no search — build (once, cached in the run) a norm-title -> forum index."""
    os.makedirs(f"{run}/review-cache", exist_ok=True)
    p = f"{run}/review-cache/venue-index-{venueid.replace('/', '_')}.json"
    if os.path.exists(p):
        return json.load(open(p))
    idx, offset = {}, 0
    while True:
        time.sleep(PACE)
        batch = client(2).get_notes(content={"venueid": venueid}, limit=1000, offset=offset)
        for n in batch:
            idx[_norm(_val(n.content.get("title", "")))] = n.forum
        if len(batch) < 1000:
            break
        offset += 1000
    json.dump(idx, open(p, "w"))
    return idx


def resolve_v2(run, title, year):
    for venue in (f"ICLR.cc/{year}/Conference", f"NeurIPS.cc/{year}/Conference",
                  f"ICLR.cc/{year + 1}/Conference"):
        try:
            idx = venue_index(run, venue)
        except Exception:
            continue
        f = idx.get(_norm(title))
        if f:
            return f
    return None


def fetch_forum(run, forum, ver):
    os.makedirs(f"{run}/review-cache", exist_ok=True)
    p = f"{run}/review-cache/{forum}.json"
    if os.path.exists(p):
        return json.load(open(p))
    time.sleep(PACE)
    notes = client(ver).get_notes(forum=forum)
    raw = [{"id": n.id, "invitation": getattr(n, "invitation", None) or
            (n.invitations[0] if getattr(n, "invitations", None) else ""),
            "invitations": getattr(n, "invitations", None),
            "signatures": n.signatures, "content": {k: _val(v) for k, v in n.content.items()}}
           for n in notes]
    json.dump(raw, open(p, "w"))
    return raw


def normalize(raw):
    revs, meta, decision = [], None, None
    for n in raw:
        invs = " ".join(n.get("invitations") or [n.get("invitation") or ""])
        c = n["content"]
        if "Official_Review" in invs:
            text = " ".join(str(c.get(k, "")) for k in
                            ("review", "summary", "strengths", "weaknesses", "main_review",
                             "strength_and_weaknesses", "summary_of_the_review",
                             "questions", "limitations") if c.get(k))
            revs.append({"signature": (n["signatures"] or ["?"])[0].split("/")[-1],
                         "rating": c.get("rating") or c.get("recommendation"),
                         "text": text})
        elif "Meta_Review" in invs or "Meta-Review" in invs:
            meta = str(c.get("metareview") or c.get("metareview:") or c.get("comment") or "")
        elif "Decision" in invs:
            decision = c.get("decision")
        elif ("Blind_Submission" in invs or "/Submission" in invs) and not decision:
            # v2 carries the outcome in the submission's venue field ("ICLR 2024 spotlight")
            v = c.get("venue")
            if v and any(w in str(v).lower() for w in ("accept", "poster", "oral", "spotlight", "reject")):
                decision = v
    return revs, meta, decision


def fetch_one(run, title, year=None, corpus_id=None, dblp=None):
    """Resolution ladder with ESCALATION: a resolved forum with ZERO official reviews is a
    mis-resolution (measured: version multiplicity — S2 carries the arXiv year, the venue year
    may differ; v2 hosting starts ~2023, NeurIPS 2023 included), so keep trying candidates and
    prefer the first forum that actually carries official reviews."""
    y = int(year) if year else None
    cands = []
    if y and y >= 2023:
        cands += [("v2", yy) for yy in (y, y + 1)]
        cands += [("v1", None)]
    else:
        cands += [("v1", None)]
        if y:
            cands += [("v2", yy) for yy in (max(y, 2023), max(y, 2023) + 1)]
    best = None
    # rung 0: deterministic id-chain (no search) — measured: exact for ICLR conf-keyed papers
    f0 = resolve_dblp(run, corpus_id=corpus_id, dblp_key=dblp)
    if f0:
        for ver in (1, 2):
            try:
                raw = fetch_forum(run, f0, ver)
            except Exception:
                continue
            revs, meta, decision = normalize(raw)
            if revs:
                return {"corpusId": corpus_id, "title": title, "forum": f0, "api": f"v{ver}",
                        "decision": decision, "n_reviews": len(revs), "reviews": revs,
                        "meta_review": meta}
    for api, yy in cands:
        if api == "v2":
            f2 = resolve_v2(run, title, yy)
            forums = [f2] if f2 else []
        else:
            forums = resolve_v1(title)
        for forum in forums:
            ver = 2 if api == "v2" else 1
            raw = fetch_forum(run, forum, ver)
            revs, meta, decision = normalize(raw)
            rec = {"corpusId": corpus_id, "title": title, "forum": forum, "api": f"v{ver}",
                   "decision": decision, "n_reviews": len(revs), "reviews": revs,
                   "meta_review": meta}
            if revs:
                return rec
            best = best or rec  # reviewless copy: keep as fallback, keep escalating
    return best or {"corpusId": corpus_id, "title": title, "forum": None,
                    "note": "unresolved — not an OpenReview venue, or title mismatch"}


def _emit(run, r, i=None, n=None):
    """STREAMING: each row is appended + printed as it completes (a batch that dies keeps
    everything done so far; progress is watchable). Caches were always per-fetch."""
    with open(f"{run}/reviews.jsonl", "a") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    pre = f"[{i}/{n}] " if i else ""
    print(pre + (r.get("forum") or "UNRESOLVED"), f"reviews={r.get('n_reviews', 0)}",
          str(r.get('decision') or '')[:30], "|", r["title"][:55], flush=True)


if __name__ == "__main__":
    cmd, run = sys.argv[1], sys.argv[2]
    if cmd == "fetch":
        a = sys.argv
        title = a[a.index("--title") + 1]
        year = a[a.index("--year") + 1] if "--year" in a else None
        cid = a[a.index("--corpus-id") + 1] if "--corpus-id" in a else None
        _emit(run, fetch_one(run, title, year, cid))
    elif cmd == "batch":
        items = [json.loads(l) for l in open(sys.argv[3]) if l.strip()]
        for i, r in enumerate(items, 1):
            _emit(run, fetch_one(run, r["title"], r.get("year"), r.get("corpusId"), r.get("dblp")), i, len(items))
