"""fulltext.py — fetch + CACHE paper full text, section-aware.

Some threads are FULL-TEXT-MANDATORY: the answer fields live in the paper body, not the abstract
(resources used, provenance relations, verbatim procedure passages, mechanism details). Decide the
evidence tier per thread (see references/fulltext-at-scale.md); when full text is needed, fetch
ONCE into the run's cache and let every extraction pass read the cache offline.

Source ladder: arxiv HTML -> ar5iv -> ACL Anthology -> openAccessPdf -> None (caller falls back to abstract / flags
unreachable — report the reachability rate honestly; expect ~90% for arXiv-era corpora, less
for older/closed venues).

Usage:
    from fulltext import fetch, sections
    text = fetch(corpus_id, arxiv_id, cache_dir="<run>/fulltext-cache")
    secs = sections(text, want=("data", "training", "architecture"))   # targeted extraction input

CLI:  python fulltext.py --cache <dir> <corpusId> <arxivId>
"""
from __future__ import annotations
import os, re, urllib.request


def _get_raw(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research; fulltext-cache)"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def _get(url, timeout=60):
    return _get_raw(url, timeout).decode("utf-8", "replace")


def _html_to_text(html):
    """Strip HTML but keep section headings as markdown '## ' so sections survive."""
    html = re.sub(r"<(script|style|nav|footer)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>",
                  lambda m: f"\n\n## {re.sub('<[^>]+>', '', m.group(2)).strip()}\n",
                  html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&#\d+;|&[a-z]+;", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n\s*\n\s*\n+", "\n\n", html)
    return html.strip()


def fetch(corpus_id, arxiv_id, cache_dir, refresh=False, acl_id=None, oa_url=None):
    """Return cleaned full text (cache-first). Writes <cache_dir>/<corpusId>.md. None if unreachable.
    Ladder: arxiv HTML -> ar5iv -> ACL Anthology (acl_id from S2 externalIds.ACL) -> open-access
    URL (oa_url from S2 openAccessPdf.url) -> None. HTML sources parse directly; PDF sources are
    SAVED to <cache_dir>/<corpusId>.pdf for the pdf-extraction path and return None here (report
    them as pdf-cached, not unreachable). Measured: arxiv-only reached ~78% on a BERT-era ACL
    corpus; these rungs exist to close that gap."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{corpus_id}.md")
    if os.path.exists(path) and not refresh:
        return open(path).read()
    urls = []
    if arxiv_id:
        aid = arxiv_id.split("v")[0]
        urls += [f"https://arxiv.org/html/{arxiv_id}", f"https://arxiv.org/html/{aid}",
                 f"https://ar5iv.labs.arxiv.org/html/{aid}"]
    if acl_id:
        urls += [f"https://aclanthology.org/{acl_id}.pdf"]  # PDF only — the landing page is
        # abstract+nav and must NOT masquerade as body text
    if oa_url:
        urls += [oa_url]
    for url in urls:
        try:
            raw = _get_raw(url)
            body = raw.decode("utf-8", "replace")
            if raw.lstrip()[:5] == b"%PDF-" or url.endswith(".pdf"):
                pdf_path = os.path.join(cache_dir, f"{corpus_id}.pdf")
                # RAW bytes end-to-end — the old text-mode decode+write corrupted every
                # cached PDF (bug found by a live acquisition round)
                with open(pdf_path, "wb") as f:
                    f.write(raw)
                continue  # cached for pdf-extraction; keep trying HTML rungs
            if len(body) < 2000:          # stub / error page
                continue
            txt = _html_to_text(body)
            if len(txt) < 1500:
                continue
            hdr = f"<!-- source: {url} | corpusId {corpus_id} | arxiv {arxiv_id} -->\n\n"
            open(path, "w").write(hdr + txt)
            return hdr + txt
        except Exception:
            continue
    return None


def sections(text, want, cap=4000):
    """Split cached text on '## ' headers; return {heading: body} for headings matching `want`.

    CAVEAT: heading-matching is heuristic — non-standard headings or HTML-conversion loss can
    miss the target section. ALWAYS fall back (pass more of the paper, or flag digest-thin) when
    nothing matches; digest quality gates extraction quality."""
    parts = re.split(r"\n## ", text)
    out = {}
    for p in parts:
        head = p.split("\n", 1)[0].strip().lower()
        if any(w in head for w in want):
            out[head[:60]] = p[:cap]
    return out


def digest(text, want, per_section=1800, total=7000, fallback_head=4000):
    """Compact per-paper extraction input: matched sections capped, else head-of-paper fallback.

    `want` is REQUIRED and thread-specific: derive the section keywords from your thread.json
    extraction_schema (which sections would hold each field?). There is deliberately no default —
    a generic default would silently shape digests for the wrong thread."""
    secs = sections(text, want, cap=per_section)
    d = "".join(f"\n### {h}\n{b}" for h, b in list(secs.items())[:5])
    return d[:total] if d else text[:fallback_head]


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    cache = a[a.index("--cache") + 1]
    rest = [x for i, x in enumerate(a) if x != "--cache" and (i == 0 or a[i - 1] != "--cache")]
    t = fetch(rest[0], rest[1], cache)
    print(f"{rest[0]}: {'FETCHED ' + str(len(t)) + ' chars' if t else 'UNREACHABLE'}")
    if t:
        print("sections:", list(sections(t, ("data", "training", "architecture", "model")))[:8])
