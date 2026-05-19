---
name: local-paper-index
description: Build a searchable Asta document index from a collection of local PDF files. Use when the user asks to "index these PDFs", "put these PDFs into an Asta index", "index these PDFs using Asta", "build a local paper index", "make these PDFs searchable", or "create an index from these papers".
metadata:
  internal: true
allowed-tools: Bash(asta pdf-extraction *) Bash(asta documents *) Bash(python3 *) Bash(bash *) Bash(find *) Bash(ls *) Bash(wc *) Bash(du *) Bash(mv *) Bash(cp *) Bash(cat *) Bash(mkdir *) Read(*) Write(*) Glob(*)
---

# Local PDF Index Builder

Build a searchable Asta document index from a collection of local PDF files. Each PDF is converted to markdown, split into ~2000-character chunks, and written as documents to an asta-documents YAML index — enabling semantic search across the full text of the collection.

## Installation

This skill requires the `asta` CLI:

```bash
# Install/reinstall at the correct version
PLUGIN_VERSION=0.17.1
if [ "$(asta --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" != "$PLUGIN_VERSION" ]; then
  uv tool install --force git+https://github.com/allenai/asta-plugins.git@v$PLUGIN_VERSION
fi
```

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/)


## Assets

This skill includes standalone scripts in the `assets/` directory:

| Script | Purpose |
|--------|---------|
| `assets/extract-pdfs.sh` | Convert PDFs to markdown via `asta pdf-extraction remote` |
| `assets/chunk-and-index.py` | Chunk markdown files and write the YAML index directly |
| `assets/warm-cache.sh` | Run an initial search to build the search cache |

Locate the assets directory relative to this skill file. The scripts are self-contained and can be copied to the working directory or run in place.

## Procedure

### Step 0: Interview the user for paths and collection name

Before starting, ask the user for **four things**:

1. **PDF directory** — Where are the PDFs?
2. **Markdown output directory** — Where should extracted markdown go?
3. **Collection name** — A short label for the collection (e.g., `my-papers`, `cs-reading-list`).
4. **Include images?** — Whether to extract and save images embedded in the PDFs alongside the markdown. Images are useful for papers with figures/diagrams but increase storage. Default: no.

**Suggest a directory layout** where the PDFs and markdown live as siblings under a common parent, with the index file alongside them. For example, if the PDFs are at `/data/papers/pdfs/`:

```
/data/papers/                          # DATASET_ROOT — parent of everything
├── pdfs/                              # PDF_DIR (user already has this)
├── markdown/                          # MARKDOWN_DIR (suggested: sibling of pdfs/)
│   ├── paper1.md                      # without --images: flat .md files
│   ├── paper2.md
│   ├── paper3/                        # with --images: per-PDF subdirectories
│   │   ├── paper3.md
│   │   └── img-0.jpeg
│   └── ...
└── index.yaml                         # INDEX_PATH (auto-created here)
```

This layout matters because the index stores **relative paths** to the markdown files. Keeping everything under one root makes the index portable and git-friendly.

**Key rules for the suggestion:**
- The markdown directory should be **adjacent to the PDF directory**, not inside `.asta`.
- The `DATASET_ROOT` is the parent directory that contains both `PDF_DIR` and `MARKDOWN_DIR`.
- The index lives at `DATASET_ROOT/index.yaml`.
- If the user's PDFs are at `/home/user/research/pdfs`, suggest `/home/user/research/markdown` and `/home/user/research/index.yaml`.

Once the user confirms (or provides their own paths), set these variables:

```bash
PDF_DIR="/data/papers/pdfs"                               # user-provided
MARKDOWN_DIR="/data/papers/markdown"                       # user-confirmed
DATASET_ROOT="/data/papers"                                # parent of both
INDEX_PATH="$DATASET_ROOT/index.yaml"                      # derived
COLLECTION="my-papers"                                     # user-chosen
IMAGES=false                                                # true if user wants images
```

### Step 1: Discover PDFs and show estimates

```bash
PDF_COUNT=$(find "$PDF_DIR" -name "*.pdf" -type f | wc -l)
TOTAL_SIZE=$(find "$PDF_DIR" -name "*.pdf" -type f -exec du -ch {} + | tail -1 | awk '{print $1}')
echo "Found $PDF_COUNT PDFs ($TOTAL_SIZE total)"
```

**Present this estimate to the user before proceeding:**

| Metric | Estimate |
|--------|----------|
| PDFs found | N files |
| Total size on disk | X MB |
| Extraction time | ~2-5 min per 10-page PDF (remote API); faster with olmocr for batches >20 |
| Chunking + indexing | ~1-2 seconds per PDF |
| Index storage | ~2-3x the extracted text size (markdown files + YAML with chunk text) |
| Cache warm-up | 5-30 seconds (one-time, after indexing) |
| **Total estimated time** | **Dominated by extraction: roughly N_papers x 3 min** |

Ask the user to confirm before starting, especially for large collections (>20 PDFs).

### Step 2: Extract PDFs to markdown

```bash
# Without images (flat layout: markdown/paper.md)
bash /path/to/assets/extract-pdfs.sh "$PDF_DIR" "$MARKDOWN_DIR"

# With images (per-PDF subdirectories: markdown/paper/paper.md + images)
bash /path/to/assets/extract-pdfs.sh --images "$PDF_DIR" "$MARKDOWN_DIR"
```

Pass `--images` only if the user opted in during Step 0. When `--images` is used, each PDF gets its own subdirectory under `MARKDOWN_DIR` to avoid image filename collisions across PDFs. The chunking script in Step 3 handles both layouts automatically.

The script:
- Skips PDFs whose markdown already exists (resumable)
- Handles large PDFs (>50 pages) by extracting in 50-page increments
- Reports progress and counts

**For large batches (>20 PDFs)**, `asta pdf-extraction olmocr` with `--workers` is significantly faster. See the pdf-extraction skill for details.

### Step 3: Chunk and build index

```bash
uv run --with pyyaml python3 /path/to/assets/chunk-and-index.py "$COLLECTION" "$MARKDOWN_DIR" --index-path "$INDEX_PATH"
```

The `--index-path` argument is **required**. The script:
- Computes paths relative to the index file's directory, storing **relative paths** in the `url` field — making the index portable across machines
- Reads each markdown file, splits into ~2000-char chunks at paragraph/sentence boundaries
- Writes all documents to the index YAML in a single pass
- Preserves any existing documents in the index (appends, does not overwrite)
- Skips PDFs already indexed for this collection (safe to re-run)
- Each document gets:
  - **Shared PDF metadata:** `source_pdf`, `collection` (in `extra`)
  - **Per-chunk metadata:** `chunk_index`, `total_chunks`, `chunk_chars`, `chunk_offset`, `file_chars` (in `extra`)
  - **Tags:** `<collection-name>`, `pdf-index`

Options:
- `--chunk-size 2000` — adjust chunk size (default 2000 chars)

### Step 4: Warm the search cache

```bash
bash /path/to/assets/warm-cache.sh "$DATASET_ROOT"
```

The argument is **required**:
- `$DATASET_ROOT` — the root directory containing `index.yaml`

**This step is required.** The first search after indexing builds the internal BM25 + embedding indexes. Without warming, the user's first real search will be unexpectedly slow.

### Step 5: Report results

```bash
asta documents --root "$DATASET_ROOT" list --tags="$COLLECTION"
asta documents --root "$DATASET_ROOT" show
```

Tell the user:
- Number of PDFs processed and chunks created
- Dataset root: the `DATASET_ROOT` path
- Index location: the `INDEX_PATH`
- Collection tag for filtering: the chosen collection name
- How to search: `asta documents --root "$DATASET_ROOT" search --summary="query" --tags="COLLECTION"`

## Searching the Index

After building, search across all indexed PDFs:

```bash
# Semantic search within the collection
asta documents --root "$DATASET_ROOT" search --summary="neural network architecture" --tags="my-papers"

# With relevance scores
asta documents --root "$DATASET_ROOT" search --summary="attention mechanism" --tags="my-papers" --show-scores

# Filter by source PDF
asta documents --root "$DATASET_ROOT" search --extra=".source_pdf contains some-paper"

# List all documents in the collection
asta documents --root "$DATASET_ROOT" list --tags="my-papers"
```

## Storage Estimates

| Collection size | Approx. index size | Approx. markdown size |
|----------------|--------------------|-----------------------|
| 10 PDFs (~10 pp each) | 2-5 MB | 1-3 MB |
| 50 PDFs (~10 pp each) | 10-25 MB | 5-15 MB |
| 100 PDFs (~10 pp each) | 20-50 MB | 10-30 MB |

Total storage is roughly **2-3x the extracted text** (markdown files + index YAML with chunk text in the `summary` field).

## Time Estimates

| Stage | Per PDF | Notes |
|-------|---------|-------|
| Extraction (remote) | 2-5 min / 10 pages | API-bound; 50-page limit per call |
| Extraction (olmocr) | 10-20 sec / page, parallel | Better for >20 PDFs |
| Chunking + indexing | 1-2 seconds | Single YAML write, fast |
| Cache warming | 5-30 seconds total | One-time after indexing |

## Important Notes

- **Warm the cache.** The first `asta documents search --summary=...` builds the search index. Always run the warm-cache script after indexing.
- **Chunk size tradeoff.** 2000 chars balances search precision with context. Smaller chunks = more precise hits, less context. Larger chunks = more context, diluted relevance.
- **Resumable.** Both extraction and indexing skip already-processed files. Safe to re-run after interruption.
- **Index is append-only.** The chunking script preserves existing documents in the index. To rebuild from scratch, delete `index.yaml` first.
- **PyYAML required.** The chunking script needs `pyyaml`. Install with `pip install pyyaml` or `uv pip install pyyaml` if not available.
- **Relative paths.** The index stores relative paths (e.g., `markdown/paper.md`) so the dataset is portable. This requires the markdown directory to be under the same directory as the index file.
