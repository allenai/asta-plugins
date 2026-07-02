#!/usr/bin/env python3
"""Download paywalled PDFs by driving a real browser via Playwright.

Used after `download-pdfs.py` has identified papers it could not retrieve
via stdlib (because they are paywalled or because the publisher blocks
non-browser clients). This script opens a Chromium window backed by a
**persistent user profile**, so institutional / SSO logins persist between
runs — the user authenticates once per publisher.

Run with:
    uv run --with playwright python3 browser-download.py <output-dir> \
        --manifest <manifest.json>

Or for a single ad-hoc URL:
    uv run --with playwright python3 browser-download.py <output-dir> \
        --url <landing-or-pdf-url> --filename <name.pdf>

First-time setup (downloads the bundled Chromium):
    uv run --with playwright playwright install chromium

Or pass --channel chrome to use the system Chrome instead of bundled Chromium
(no `playwright install` needed; less likely to be flagged as automation).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import (
        TimeoutError as PWTimeout,
    )
    from playwright.sync_api import (
        sync_playwright,
    )
except ImportError:
    print(
        "playwright is not installed. Re-run with:\n"
        "  uv run --with playwright python3 browser-download.py ...",
        file=sys.stderr,
    )
    sys.exit(2)


DEFAULT_PROFILE = "~/.cache/asta/pdf-download-profile"
DEFAULT_TIMEOUT_SEC = 600  # 10 minutes per paper for user interaction


def filename_for_entry(entry: dict) -> str:
    ext = entry.get("external_ids") or {}
    for key in ("ArXiv", "DOI", "CorpusId", "PubMed"):
        if ext.get(key):
            stem = f"{key}_{ext[key]}"
            break
    else:
        stem = (entry.get("title") or entry.get("input") or "paper")[:120]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")
    return f"{stem or 'paper'}.pdf"


def landing_urls_for_entry(entry: dict) -> list[str]:
    """Return ordered list of candidate URLs to try for an unresolved paper.

    Primary is the open-access PDF URL (if Phase 1 found one) — it may have
    failed at the network level (Cloudflare, bot detection, transient 5xx)
    and may succeed through a real browser session.

    Fallbacks: DOI URL, arXiv abs page, PubMed, PMC, and finally any
    landing_url stashed by Phase 1. The DOI URL is especially useful when
    the OA host (e.g. Europe PMC) returns 5xx — doi.org redirects to the
    publisher's canonical landing page where the user can authenticate.
    """
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str | None) -> None:
        if u and u not in seen:
            urls.append(u)
            seen.add(u)

    add(entry.get("open_access_pdf_url"))
    ext = entry.get("external_ids") or {}
    if doi := ext.get("DOI"):
        add(f"https://doi.org/{doi}")
    if arxiv := ext.get("ArXiv"):
        add(f"https://arxiv.org/abs/{arxiv}")
    if pmid := ext.get("PubMed"):
        add(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
    if pmcid := ext.get("PubMedCentral"):
        add(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/")
    add(entry.get("landing_url"))
    return urls


def looks_like_pdf(content_type: str, body: bytes) -> bool:
    if "pdf" in (content_type or "").lower():
        return True
    return body[:4] == b"%PDF"


def try_request_url(context, url: str, dest: Path) -> bool:
    """Fetch `url` using the persistent context's cookies. Returns True on success."""
    try:
        resp = context.request.get(url, max_redirects=10)
    except Exception as e:
        print(f"    request.get failed: {e}", file=sys.stderr)
        return False
    if not resp.ok:
        print(f"    request.get returned {resp.status}", file=sys.stderr)
        return False
    body = resp.body()
    ctype = resp.headers.get("content-type", "")
    if not looks_like_pdf(ctype, body):
        print(
            f"    response was not a PDF (Content-Type: {ctype or 'unknown'})",
            file=sys.stderr,
        )
        return False
    dest.write_bytes(body)
    return True


def extract_citation_pdf_url(page) -> str | None:
    """Many academic publishers expose the PDF URL via meta[name=citation_pdf_url]."""
    try:
        return page.locator("meta[name=citation_pdf_url]").first.get_attribute(
            "content", timeout=2000
        )
    except Exception:
        return None


def _safe_close(page) -> None:
    try:
        if not page.is_closed():
            page.close()
    except Exception:
        pass


def download_one(context, landing_urls: list[str], dest: Path, timeout_s: int) -> str:
    """Try each candidate URL, then open one in a browser tab and poll for a PDF.

    Returns one of: 'downloaded', 'skipped' (user closed the tab), 'failed'
    (timed out without a PDF appearing). No TTY interaction is needed —
    the user signals "done" implicitly by triggering a download in the
    browser, or "skip" by closing the tab.
    """
    # Try each URL via the context's request API first. This uses the
    # persistent profile's cookies + a real-browser TLS fingerprint, which
    # is enough for many publishers that bot-block plain urllib but don't
    # require an interactive session. No browser window needed in those cases.
    for url in landing_urls:
        if try_request_url(context, url, dest):
            print("  resolved without opening browser", file=sys.stderr)
            return "downloaded"

    # All request.get calls failed. Pick a URL to open in the browser.
    # Prefer the DOI URL (publisher's canonical landing page) over a direct
    # OA PDF URL that already errored — the DOI URL is where the user can
    # authenticate and navigate to the paper's PDF.
    browser_url = next(
        (u for u in landing_urls if "doi.org/" in u),
        landing_urls[0],
    )
    landing_url = browser_url

    page = context.new_page()

    # Capture any download the user triggers (clicking the publisher's
    # "Download PDF" button, etc.). Listen at the *context* level so we
    # also catch downloads from new tabs opened via target="_blank" or
    # window.open — publisher "Download PDF" links often work that way.
    download_result = {"saved": False}

    def on_download(dl):
        try:
            dl.save_as(str(dest))
            download_result["saved"] = True
            print("    captured user-triggered download", file=sys.stderr)
        except Exception as e:
            print(f"    saving download failed: {e}", file=sys.stderr)

    context.on("download", on_download)
    try:
        print(f"  opening: {landing_url}", file=sys.stderr)
        try:
            page.goto(landing_url, wait_until="domcontentloaded", timeout=60000)
        except PWTimeout:
            print("    initial page load timed out (continuing)", file=sys.stderr)
        except Exception as e:
            print(f"    page.goto failed: {e}", file=sys.stderr)

        print(
            f"  >> In the browser: authenticate if needed, then either let the\n"
            f"     script auto-detect the PDF or click the publisher's download\n"
            f"     button. Close the tab to skip this paper.\n"
            f"     Waiting up to {timeout_s}s.",
            file=sys.stderr,
        )

        # Cache URLs we've tried so we don't refetch the same failing one each tick.
        tried: set[str] = {landing_url}

        def try_url(url: str | None) -> bool:
            if not url or url in tried:
                return False
            tried.add(url)
            return try_request_url(context, url, dest)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if download_result["saved"]:
                    _safe_close(page)
                    return "downloaded"
                if page.is_closed():
                    # User closed the original tab. If they navigated to a
                    # new tab (target=_blank link), give the download event
                    # a brief moment to fire before we call it skipped.
                    time.sleep(2)
                    if download_result["saved"]:
                        return "downloaded"
                    return "skipped"

                current = page.url
                if (
                    current.lower().endswith(".pdf") or "/pdf/" in current.lower()
                ) and try_url(current):
                    _safe_close(page)
                    return "downloaded"

                meta_pdf = extract_citation_pdf_url(page)
                if meta_pdf and try_url(meta_pdf):
                    _safe_close(page)
                    return "downloaded"

                page.wait_for_timeout(3000)
            except KeyboardInterrupt:
                _safe_close(page)
                raise
            except Exception as e:
                if page.is_closed():
                    return "skipped"
                print(f"    poll error (continuing): {e}", file=sys.stderr)
                time.sleep(2)

        print("    timed out waiting for a PDF", file=sys.stderr)
        _safe_close(page)
        return "failed"
    finally:
        try:
            context.remove_listener("download", on_download)
        except Exception:
            pass


def collect_jobs(args) -> list[dict]:
    """Build the list of (url, filename, entry?) jobs from manifest or --url."""
    jobs: list[dict] = []
    if args.manifest:
        manifest = json.loads(Path(args.manifest).read_text())
        for entry in manifest.get("entries", []):
            status = entry.get("status")
            if status not in ("paywalled", "download-failed", "resolve-failed"):
                continue
            urls = landing_urls_for_entry(entry)
            if not urls:
                print(
                    f"  [skip] no URL available for: {entry.get('input')!r}",
                    file=sys.stderr,
                )
                continue
            jobs.append(
                {
                    "urls": urls,
                    "filename": filename_for_entry(entry),
                    "entry": entry,
                }
            )
    elif args.url:
        jobs.append(
            {
                "urls": [args.url],
                "filename": args.filename or "paper.pdf",
                "entry": None,
            }
        )
    return jobs


def check_display() -> None:
    """Fail fast on headless Linux where a headed browser cannot open."""
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        print(
            "ERROR: no DISPLAY / WAYLAND_DISPLAY is set; cannot launch a headed\n"
            "browser on this host. Run this script on a machine with a display,\n"
            "or set up the persistent profile elsewhere and copy it over.",
            file=sys.stderr,
        )
        sys.exit(2)


def update_manifest(manifest_path: Path, results: dict[str, dict]) -> None:
    """Merge `results` (keyed by manifest entry input) back into the manifest."""
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception:
        return
    counts = manifest.get("counts", {})
    for entry in manifest.get("entries", []):
        key = entry.get("input")
        if key not in results:
            continue
        new_status = results[key].get("status")
        if not new_status:
            continue
        old_status = entry.get("status")
        if old_status in counts:
            counts[old_status] -= 1
        entry["status"] = new_status
        if path := results[key].get("path"):
            entry["path"] = path
        counts[new_status] = counts.get(new_status, 0) + 1
    manifest["counts"] = counts
    manifest_path.write_text(json.dumps(manifest, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("output_dir")
    ap.add_argument(
        "--manifest",
        help="Process all paywalled / download-failed / resolve-failed entries",
    )
    ap.add_argument("--url", help="Single landing URL to process")
    ap.add_argument("--filename", help="Filename for --url mode")
    ap.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        help=f"Persistent Chromium profile directory (default: {DEFAULT_PROFILE})",
    )
    ap.add_argument(
        "--channel",
        default=None,
        help="Playwright browser channel (e.g. 'chrome') — uses system Chrome",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"Seconds to wait per paper for a PDF (default: {DEFAULT_TIMEOUT_SEC})",
    )
    args = ap.parse_args()

    if not (args.manifest or args.url):
        ap.error("need either --manifest or --url")

    check_display()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(args.profile).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)

    jobs = collect_jobs(args)
    if not jobs:
        print("Nothing to do.", file=sys.stderr)
        return 0

    print(
        f"Will process {len(jobs)} paper(s) using profile {profile_dir}",
        file=sys.stderr,
    )
    print(
        "Logins/SSO sessions persist in that directory across runs.\n"
        "Treat it as credential material — don't share or commit it.\n",
        file=sys.stderr,
    )

    results: dict[str, dict] = {}

    with sync_playwright() as p:
        launch_kwargs = {
            "user_data_dir": str(profile_dir),
            "headless": False,
            "accept_downloads": True,
            "viewport": {"width": 1280, "height": 900},
            # Reduce Playwright's automation fingerprint so publishers
            # (Cloudflare, hCaptcha) don't loop the user through captchas
            # forever. Removes navigator.webdriver=true and the
            # "Chrome is being controlled by automated test software" banner.
            "args": ["--disable-blink-features=AutomationControlled"],
            "ignore_default_args": ["--enable-automation"],
        }
        if args.channel:
            launch_kwargs["channel"] = args.channel
        context = p.chromium.launch_persistent_context(**launch_kwargs)

        try:
            for i, job in enumerate(jobs, 1):
                dest = out_dir / job["filename"]
                print(f"\n[{i}/{len(jobs)}] {job['filename']}", file=sys.stderr)
                if dest.exists() and dest.stat().st_size > 0:
                    print("  already exists, skipping", file=sys.stderr)
                    status = "already-downloaded"
                else:
                    try:
                        status = download_one(context, job["urls"], dest, args.timeout)
                    except KeyboardInterrupt:
                        print("\nInterrupted by user.", file=sys.stderr)
                        break
                    except Exception as e:
                        print(f"  error: {e}", file=sys.stderr)
                        status = "failed"
                if job["entry"] is not None:
                    results[job["entry"].get("input")] = {
                        "status": status,
                        "path": str(dest) if status == "downloaded" else None,
                    }
        finally:
            context.close()

    if args.manifest and results:
        update_manifest(Path(args.manifest), results)
        print(f"\nManifest updated: {args.manifest}", file=sys.stderr)

    summary = {"downloaded": 0, "failed": 0, "already-downloaded": 0}
    for r in results.values():
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    print(json.dumps(summary, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
