---
name: pdf-download
description: Download PDFs for a list of academic papers identified by title, DOI, arXiv ID, or other paper IDs. Use when the user asks to "download these papers", "grab the PDFs", "fetch full text for this list", or supplies a list of citations and wants the source PDFs on disk. Resolves open-access PDFs automatically and drives a real browser (via Playwright, with a persistent profile) so the user can authenticate to paywalled publishers.
allowed-tools: Bash(asta papers *) Bash(python3 *) Bash(uv run *) Bash(cat *) Bash(jq *) Bash(mkdir *) Bash(ls *) Bash(wc *) Bash(mv *) Bash(cp *) Bash(find *) Read(*) Write(*) Glob(*)
---

# Download PDFs for a Paper List

Given a list of academic papers (titles, DOIs, arXiv IDs, etc.) and a target
directory, download the source PDFs.

The skill works in two phases:

1. **Fast path** — fetch open-access PDFs directly (arXiv, PMC, anything
   surfaced by Semantic Scholar's `openAccessPdf.url` and served as a real
   PDF). Pure stdlib, no browser, ~1s per paper.
2. **Browser path** — for everything else (paywalled publishers, Cloudflare-
   protected hosts, JS-redirected logins), launch Chromium via Playwright
   with a **persistent user profile** so the user can complete institutional
   SSO / publisher login in a real browser window. Sessions persist across
   runs — the user logs in to each publisher once.

Real publishers (Elsevier, Springer/Nature, Wiley, ACS, IEEE…) fingerprint
TLS and JS environments, so a `urllib`/`curl`-with-pasted-cookies approach
fails on most of them. A real browser is what works.

## Assets

| Script | Purpose |
|--------|---------|
| `assets/download-pdfs.py` | Phase 1: resolve identifiers via `asta papers`, download open-access PDFs (stdlib) |
| `assets/browser-download.py` | Phase 2: drive Chromium via Playwright with a persistent profile |

Locate the assets directory relative to this skill file.

## Procedure

### Step 0: Interview the user

Confirm three things before starting:

1. **Input list** — Where is the list of papers? Either a path to a text file
   (one identifier per line) or content the user has pasted. Accepted forms
   per line: `DOI:...`, `ARXIV:...`, `CorpusId:...`, `PMID:...`, `URL:...`,
   bare arXiv id (`2005.14165`), bare DOI (`10.x/...`), or plain title.
   Blank lines and `#` comments are ignored.
2. **Output directory** — Where should PDFs land? Default `./pdfs/`.
3. **Browser path expectations** — Tell the user that paywalled papers will
   open a Chromium window where they will log in (institutional SSO, publisher
   account, etc.) once per publisher; the login persists for future runs.
   Confirm they're on a machine with a display (not a headless SSH session).

If the user pasted the list inline, write it to `<output-dir>/paper-list.txt`
before running.

### Step 1: Fast path — download what's open access

```bash
INPUT="/path/to/paper-list.txt"
OUTPUT_DIR="/path/to/pdfs"
ASSETS="/path/to/skill/assets"   # this skill's assets/ directory

mkdir -p "$OUTPUT_DIR"
python3 "$ASSETS/download-pdfs.py" "$INPUT" "$OUTPUT_DIR"
```

Writes `$OUTPUT_DIR/manifest.json`. Per-paper statuses:

| Status | Meaning | Next phase |
|--------|---------|-----------|
| `downloaded` | PDF saved to `path` | done |
| `already-downloaded` | File at `path` already existed | done |
| `paywalled` | No open-access URL in Semantic Scholar | Phase 2 (browser) |
| `download-failed` | Open-access URL returned an error or non-PDF | Phase 2 (browser) |
| `resolve-failed` | `asta papers` could not match the identifier | flag for the user |
| `skipped` | Phase 2 only — user closed the tab without downloading | flag for the user |

Show the user the counts and the manifest path. If the counts include
non-trivial `paywalled` / `download-failed`, proceed to Phase 2.

### Step 2: Browser path — authenticated downloads via Playwright

#### One-time setup

The script auto-installs the `playwright` Python package via `uv`, but the
**browser binary** is a separate download (~150 MB). Run once:

```bash
uv run --with playwright playwright install chromium
```

Alternatively, skip this step and use the user's installed Chrome by passing
`--channel chrome` (see below). Chrome usually has a more "real" fingerprint
and is less likely to be flagged as automation.

#### Run the browser downloader

```bash
uv run --with playwright python3 "$ASSETS/browser-download.py" \
  "$OUTPUT_DIR" --manifest "$OUTPUT_DIR/manifest.json"

# Or, to use the user's installed Chrome instead of bundled Chromium:
uv run --with playwright python3 "$ASSETS/browser-download.py" \
  "$OUTPUT_DIR" --manifest "$OUTPUT_DIR/manifest.json" --channel chrome
```

The script runs **non-interactively** — there is no terminal prompt. All
user interaction happens in the browser window. For each paywalled / failed
entry, the script:

1. Probes the URL via Playwright's HTTP client (with profile cookies and a
   real-browser TLS fingerprint). Many `download-failed` cases from Phase 1
   are simply blocked by TLS / header fingerprinting and succeed here with
   no visible browser at all.
2. If that fails, opens the paper's landing page (DOI URL, publisher page,
   arXiv abs page, etc.) in a real Chromium window backed by a persistent
   profile at `~/.cache/asta/pdf-download-profile/`. (Override with
   `--profile`.)
3. Polls every few seconds, watching for any of:
   - the page URL becoming a PDF
   - a `<meta name="citation_pdf_url">` tag becoming fetchable
   - a download event triggered by the user clicking the publisher's
     "Download PDF" button
4. The user authenticates in the browser if needed (institutional SSO,
   publisher account, MFA, captcha). Cookies persist in the profile, so
   subsequent papers from the same publisher need no further login.
5. Saves the PDF to `$OUTPUT_DIR/{ExternalIdKey}_{value}.pdf` and updates
   the manifest.

#### Telling the user what to do, per paper

The script does not read from stdin. The user's options, all driven from
the browser window:

- **First time visiting this publisher**: complete the institutional/SSO
  login in the tab. Once authenticated, the script's poller picks up the
  PDF automatically. If auto-detection doesn't work, the user clicks the
  publisher's "Download PDF" button and Playwright captures the download.
- **Already logged in (subsequent papers)**: the script usually resolves
  the PDF in the pre-flight `request.get` step and no browser window
  appears for that paper at all.
- **Can't or don't want to access this paper**: close the browser tab.
  The script marks it `skipped` and moves to the next.
- **Per-paper timeout**: defaults to 10 minutes. Override with
  `--timeout SECONDS`.

#### When the browser is not available

If the user is on a headless machine (no `$DISPLAY` on Linux), the script
exits with an error. Run the skill on the user's laptop/desktop instead.

### Step 3: Report results

When done, tell the user:

- How many PDFs were downloaded automatically vs via the browser vs still
  missing.
- Output directory and manifest path.
- That the persistent profile at `~/.cache/asta/pdf-download-profile/`
  contains login cookies and should not be checked into git.

If the user wants to index the PDFs for search, suggest the
`local-paper-index` skill next.

## How identifiers are resolved

`download-pdfs.py` calls:

- `asta papers get <ID> --fields title,externalIds,openAccessPdf,...` for
  identifiers with a recognized prefix (`DOI:`, `ARXIV:`, `CorpusId:`, etc.),
  bare arXiv IDs like `2005.14165`, and bare DOIs like `10.x/...`.
- `asta papers search "<title>" --limit 1` for everything else; the top
  match is used.

For ambiguous titles, prefer DOIs or arXiv IDs from the user. If the
manifest's resolved `title` doesn't match what the user intended, ask them
for a more specific identifier and re-run.

## Persistent profile

The Playwright profile dir holds:
- Cookies for every publisher the user has logged into
- Saved passwords (if the user opts in via Chromium's prompts)
- Local storage / session storage entries

**Don't commit this directory and don't share it.** It is functionally a
credential file.

Defaults to `~/.cache/asta/pdf-download-profile/`. To use a fresh profile or
isolate per-project credentials, pass `--profile /path/to/dir`.

## When to use this skill

✅ Use when:
- The user has a list of papers and wants the actual PDF files on disk
- The user wants to prepare a corpus for `local-paper-index`,
  `pdf-extraction`, or a literature analysis pipeline
- A literature search produced references the user wants offline

❌ Don't use when:
- The user only needs metadata or abstracts — use `semantic-scholar`
- The user wants text content rather than PDFs — use `pdf-extraction` after
  obtaining PDFs, or `asta papers snippet-search` for short excerpts
- The user is on a headless host with no display **and** the papers are
  paywalled (Step 2 needs a real browser)

## Notes

- The skill does **not** route through Sci-Hub or scrape behind paywalls
  automatically. All paywalled downloads require the user to be properly
  authenticated through their own institution or publisher account.
- arXiv and PMC are zero-friction — the fast path handles them entirely.
- Re-running is safe — files that already exist are skipped at both phases,
  and the manifest is rewritten in place with updated statuses.
- For very large lists (>50 papers), expect Step 1 to take a few minutes
  (one `asta papers get` call per identifier) and Step 2 to be roughly
  10–30s per paper after the first login for each publisher.
