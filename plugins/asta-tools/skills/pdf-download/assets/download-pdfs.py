#!/usr/bin/env python3
"""Download PDFs for a list of academic papers.

Reads identifiers from an input file (one per line), resolves each via
`asta papers get` (or `asta papers search` for plain titles), and downloads
the open-access PDF when available.

Usage:
    python3 download-pdfs.py <input-file> <output-dir> [--manifest <path>]

Each line of <input-file> can be:
    DOI:10.1145/3442188.3445922
    ARXIV:2005.14165
    CorpusId:215416146
    PMID:19872477
    URL:https://arxiv.org/abs/2005.14165
    2005.14165                          # bare arXiv id
    10.1145/3442188.3445922             # bare DOI
    Attention Is All You Need           # title

Blank lines and lines beginning with '#' are ignored.

The output manifest is a JSON document listing the resolved paper for each
input line, the local path of the downloaded PDF (if any), and a status
indicating whether human authentication is required.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PDF_USER_AGENT = "Mozilla/5.0 (compatible; asta-pdf-download/1.0)"
ASTA_FIELDS = "title,externalIds,openAccessPdf,isOpenAccess,year,authors,url"


def run_asta(args: list[str]) -> dict:
    """Run `asta` and parse its JSON output."""
    proc = subprocess.run(
        ["asta", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"asta {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def looks_like_doi(s: str) -> bool:
    return bool(re.match(r"^10\.\d{4,9}/", s))


def looks_like_arxiv(s: str) -> bool:
    return bool(re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", s)) or bool(
        re.match(r"^[a-z\-]+/\d{7}$", s)
    )


def normalize_id(raw: str) -> tuple[str, str]:
    """Return ('id'|'title', normalized_value) for an input line."""
    s = raw.strip()
    if not s:
        return ("skip", "")
    upper = s.upper()
    for prefix in ("DOI:", "ARXIV:", "CORPUSID:", "PMID:", "PMCID:", "URL:"):
        if upper.startswith(prefix):
            # canonicalize prefix case
            return ("id", prefix + s[len(prefix) :])
    if looks_like_arxiv(s):
        return ("id", f"ARXIV:{s}")
    if looks_like_doi(s):
        return ("id", f"DOI:{s}")
    return ("title", s)


def resolve_paper(raw: str) -> dict:
    """Resolve a single input line to a paper record via `asta papers`."""
    kind, value = normalize_id(raw)
    if kind == "skip":
        return {}
    if kind == "id":
        return run_asta(["papers", "get", value, "--fields", ASTA_FIELDS])
    # title search: take best match
    result = run_asta(
        ["papers", "search", value, "--fields", ASTA_FIELDS, "--limit", "1"]
    )
    data = result.get("data") or []
    if not data:
        raise RuntimeError(f"No search results for title: {value!r}")
    return data[0]


def safe_filename(paper: dict, fallback: str) -> str:
    """Build a stable, filesystem-safe PDF filename for a paper."""
    ext_ids = paper.get("externalIds") or {}
    for key in ("ArXiv", "DOI", "CorpusId", "PubMed"):
        if ext_ids.get(key):
            stem = f"{key}_{ext_ids[key]}"
            break
    else:
        stem = (paper.get("title") or fallback)[:120]
    # filesystem-safe: keep alnum, dash, underscore, dot; replace others with '-'
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")
    return f"{stem or 'paper'}.pdf"


def publisher_landing_url(paper: dict) -> str | None:
    """Pick a *publisher* landing URL (not semanticscholar.org).

    Semantic Scholar's `paper.url` always points at semanticscholar.org, which
    is useless for authenticating to a paywalled publisher. Prefer URLs built
    from `externalIds` (DOI, arXiv, PubMed) so the browser-driven step opens
    the publisher's own page where the user can sign in.
    """
    ext = paper.get("externalIds") or {}
    if doi := ext.get("DOI"):
        return f"https://doi.org/{doi}"
    if arxiv := ext.get("ArXiv"):
        return f"https://arxiv.org/abs/{arxiv}"
    if pmid := ext.get("PubMed"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if pmcid := ext.get("PubMedCentral"):
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
    # Last resort: S2's URL. Better than nothing for tracking, but the
    # browser step usually can't do anything useful with it.
    return paper.get("url")


def download_pdf(url: str, dest: Path) -> None:
    """Download a PDF, following redirects, raising on non-PDF responses."""
    req = urllib.request.Request(url, headers={"User-Agent": PDF_USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        ctype = resp.headers.get("Content-Type", "")
        data = resp.read()
    # Some publishers return HTML landing pages even at "PDF" URLs; flag those.
    if "pdf" not in ctype.lower() and not data.startswith(b"%PDF"):
        raise RuntimeError(
            f"URL did not return a PDF (Content-Type: {ctype or 'unknown'})"
        )
    dest.write_bytes(data)


def process_line(raw: str, out_dir: Path) -> dict:
    """Resolve and try to download one paper. Returns a manifest entry."""
    entry: dict = {"input": raw.strip()}
    try:
        paper = resolve_paper(raw)
    except Exception as e:
        entry["status"] = "resolve-failed"
        entry["error"] = str(e)
        return entry
    if not paper:
        entry["status"] = "skipped"
        return entry

    entry["paper_id"] = paper.get("paperId")
    entry["title"] = paper.get("title")
    entry["external_ids"] = paper.get("externalIds") or {}
    entry["landing_url"] = publisher_landing_url(paper)

    oa = paper.get("openAccessPdf") or {}
    pdf_url = oa.get("url") if isinstance(oa, dict) else None
    entry["open_access_pdf_url"] = pdf_url

    if not pdf_url:
        entry["status"] = "paywalled"
        return entry

    filename = safe_filename(paper, raw)
    dest = out_dir / filename
    if dest.exists() and dest.stat().st_size > 0:
        entry["status"] = "already-downloaded"
        entry["path"] = str(dest)
        return entry

    try:
        download_pdf(pdf_url, dest)
    except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
        entry["status"] = "download-failed"
        entry["error"] = str(e)
        return entry

    entry["status"] = "downloaded"
    entry["path"] = str(dest)
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", help="File with one paper identifier per line")
    ap.add_argument("output_dir", help="Directory to write downloaded PDFs")
    ap.add_argument(
        "--manifest",
        help="Path to write JSON manifest (default: <output_dir>/manifest.json)",
    )
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "manifest.json"

    lines = [
        line
        for line in Path(args.input).read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    entries = []
    counts = {
        "downloaded": 0,
        "already-downloaded": 0,
        "paywalled": 0,
        "download-failed": 0,
        "resolve-failed": 0,
    }
    for i, line in enumerate(lines, 1):
        print(f"[{i}/{len(lines)}] {line.strip()}", file=sys.stderr)
        entry = process_line(line, out_dir)
        entries.append(entry)
        status = entry.get("status", "skipped")
        counts[status] = counts.get(status, 0) + 1
        suffix = ""
        if entry.get("path"):
            suffix = f" -> {entry['path']}"
        elif entry.get("error"):
            suffix = f" ({entry['error']})"
        print(f"  {status}{suffix}", file=sys.stderr)

    manifest_path.write_text(
        json.dumps({"entries": entries, "counts": counts}, indent=2)
    )
    print(f"\nManifest: {manifest_path}", file=sys.stderr)
    print(json.dumps(counts, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
