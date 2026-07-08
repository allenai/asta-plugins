"""s2.py — shared Semantic Scholar client: CACHED, RATE-LIMITED, SERIALIZED.

Every S2 access in a corpus-research run goes through this one client. Rationale (learned the hard
way): parallel subagents each hand-rolling urllib against S2 get throttled (429/403) and re-fetch
data already pulled. Principles: fetch-once/reuse-forever (cache keyed by request), one serialized
lane with backoff, key read from env — never printed.

Usage (library):
    from s2 import S2
    s2 = S2(cache_dir="<run>/s2-cache")           # cache lives with the run (or pass a shared dir)
    s2.paper(corpus_id, fields="title,abstract,externalIds")
    s2.batch(corpus_ids, fields="title,abstract")             # chunks of 100, cached per-paper
    s2.references(corpus_id)                                  # full pagination -> [corpusIds]
    s2.citations(corpus_id)                                   # full pagination -> [corpusIds]
    s2.search(query, fields="title,corpusId,year", limit=5)   # cached by query

CLI (for quick shell use):
    python s2.py --cache <dir> paper 12345 title,abstract
    python s2.py --cache <dir> search "some query"

Env: S2_API_KEY (optional but strongly recommended; keyless is heavily throttled).
"""
from __future__ import annotations
import json, os, time, hashlib, urllib.request, urllib.parse, urllib.error

API = "https://api.semanticscholar.org/graph/v1"


class S2:
    def __init__(self, cache_dir, key=None, min_interval=1.1, tries=6):
        self.cache = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.key = key or os.environ.get("S2_API_KEY")
        self.min_interval = min_interval
        self.tries = tries
        self._last = 0.0

    # ---- plumbing ---------------------------------------------------------
    def _cache_path(self, kind, ident):
        h = hashlib.sha1(ident.encode()).hexdigest()[:16]
        safe = "".join(c if c.isalnum() else "_" for c in ident[:40])
        return os.path.join(self.cache, f"{kind}-{safe}-{h}.json")

    def _cached(self, kind, ident):
        p = self._cache_path(kind, ident)
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
        return None

    def _store(self, kind, ident, value):
        with open(self._cache_path(kind, ident), "w") as f:
            json.dump(value, f)
        return value

    def _get(self, url, data=None):
        """Serialized GET/POST with backoff. Raises RuntimeError after exhausting retries."""
        for attempt in range(self.tries):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(
                url, data=data,
                headers={**({"x-api-key": self.key} if self.key else {}),
                         **({"Content-Type": "application/json"} if data else {})})
            try:
                self._last = time.time()
                return json.load(urllib.request.urlopen(req, timeout=60))
            except urllib.error.HTTPError as e:
                if e.code in (429, 403, 500, 502, 503):
                    time.sleep(min(4 * (attempt + 1), 30))
                    continue
                raise
            except Exception:
                time.sleep(3)
                continue
        raise RuntimeError(f"S2 unavailable after {self.tries} tries: {url[:120]}")

    # ---- endpoints (all cached) -------------------------------------------
    def paper(self, corpus_id, fields="title,abstract,year,externalIds,venue,authors,referenceCount"):
        ident = f"{corpus_id}|{fields}"
        hit = self._cached("paper", ident)
        if hit is not None:
            return hit
        r = self._get(f"{API}/paper/CorpusId:{corpus_id}?fields={fields}")
        return self._store("paper", ident, r)

    def batch(self, corpus_ids, fields="title,abstract,year,externalIds"):
        """Cached per-paper; only misses hit the network (in chunks of 100)."""
        out, misses = {}, []
        for c in map(str, corpus_ids):
            hit = self._cached("paper", f"{c}|{fields}")
            if hit is not None:
                out[c] = hit
            else:
                misses.append(c)
        for i in range(0, len(misses), 100):
            chunk = misses[i:i + 100]
            r = self._get(f"{API}/paper/batch?fields={fields}",
                          data=json.dumps({"ids": [f"CorpusId:{c}" for c in chunk]}).encode())
            for c, p in zip(chunk, r):
                out[c] = self._store("paper", f"{c}|{fields}", p)
        return out

    def _paged_ids(self, corpus_id, direction):
        ident = f"{corpus_id}|{direction}"
        hit = self._cached("edges", ident)
        if hit is not None:
            return hit
        ids, off, fld = [], 0, ("citedPaper" if direction == "references" else "citingPaper")
        while True:
            r = self._get(f"{API}/paper/CorpusId:{corpus_id}/{direction}?fields=externalIds&limit=500&offset={off}")
            data = r.get("data") or []
            for x in data:
                c = ((x.get(fld) or {}).get("externalIds") or {}).get("CorpusId")
                if c:
                    ids.append(str(c))
            if len(data) < 500 or off >= 9500:
                break
            off += 500
        return self._store("edges", ident, ids)

    def references(self, corpus_id):
        return self._paged_ids(corpus_id, "references")

    def citations(self, corpus_id):
        return self._paged_ids(corpus_id, "citations")

    def search(self, query, fields="title,corpusId,year", limit=5):
        ident = f"{query}|{fields}|{limit}"
        hit = self._cached("search", ident)
        if hit is not None:
            return hit
        r = self._get(f"{API}/paper/search?" + urllib.parse.urlencode(
            {"query": query, "fields": fields, "limit": limit}))
        return self._store("search", ident, r.get("data") or [])


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    cache = args[args.index("--cache") + 1] if "--cache" in args else "./s2-cache"
    args = [a for i, a in enumerate(args) if a != "--cache" and (i == 0 or args[i - 1] != "--cache")]
    s2 = S2(cache)
    cmd = args[0]
    if cmd == "paper":
        print(json.dumps(s2.paper(args[1], args[2] if len(args) > 2 else "title,abstract,year"), indent=1))
    elif cmd == "search":
        print(json.dumps(s2.search(" ".join(args[1:])), indent=1))
    elif cmd == "references":
        print(json.dumps(s2.references(args[1])))
    elif cmd == "citations":
        print(json.dumps(s2.citations(args[1])))
    else:
        print(__doc__)
