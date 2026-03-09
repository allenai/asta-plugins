---
name: PDF Text Extraction (olmOCR)
description: Extract text from PDFs using olmOCR. Use when user asks to "extract text from PDF", "OCR a document", "read a PDF", or needs to process scanned documents.
allowed-tools:
  - Bash(asta ocr *)
  - Bash(olmocr *)
  - Read(.asta/ocr/*)
  - Read(*/markdown/*)
  - Write(.asta/ocr/*)
---

# PDF Text Extraction with olmOCR

Extract high-quality text from PDFs using the olmOCR tool. This skill uses the olmocr CLI which supports both GPU-accelerated local inference and cloud API providers.

## Quick Start (API Mode - No GPU Required)

### 1. Get an API Key

Choose an API provider:

| Provider | Cost | Speed | Signup |
|----------|------|-------|--------|
| **Cirrascale** (recommended) | $0.07/1M tokens | Fast | AI2 partner |
| DeepInfra | $0.09/1M tokens | Fast | deepinfra.com |
| Parasail | $0.10/1M tokens | Fast | parasail.io |

**Cost estimate**: ~$0.001-0.01 per typical PDF (10-50 pages)

### 2. Extract Text from PDF

The olmocr CLI will auto-install on first use. Basic usage:

```bash
# Extract using DeepInfra API
export DEEPINFRA_API_KEY="your-key-here"
asta ocr ~/workspace/output \
  --pdfs document.pdf \
  --server https://api.deepinfra.com/v1/openai \
  --api_key "$DEEPINFRA_API_KEY" \
  --markdown

# Output will be in ~/workspace/output/markdown/document.md
```

### 3. Understanding olmocr CLI

The `asta ocr` command is a passthrough to `olmocr` with this syntax:

```bash
olmocr <workspace> [OPTIONS]
```

**Key arguments:**
- `<workspace>` - Output directory (required, positional argument)
- `--pdfs` - PDF file(s) to process
- `--server` - API endpoint URL (e.g., https://api.deepinfra.com/v1/openai)
- `--api_key` - API authentication key
- `--markdown` - Generate markdown output (recommended)
- `--workers` - Parallel workers (default: 20)

## Common Workflows

### Extract Single PDF

```bash
# Create workspace and extract
WORKSPACE="$HOME/.asta/ocr/my-paper"
asta ocr "$WORKSPACE" \
  --pdfs paper.pdf \
  --server https://api.deepinfra.com/v1/openai \
  --api_key "$DEEPINFRA_API_KEY" \
  --markdown

# Read the extracted text
cat "$WORKSPACE/markdown/paper.md"
```

### Extract Multiple PDFs

```bash
# Process all PDFs in a directory
WORKSPACE="$HOME/.asta/ocr/batch"
asta ocr "$WORKSPACE" \
  --pdfs papers/*.pdf \
  --server https://api.deepinfra.com/v1/openai \
  --api_key "$DEEPINFRA_API_KEY" \
  --markdown \
  --workers 10
```

### Extract and Index in Documents

```bash
# 1. Extract text
WORKSPACE="$HOME/.asta/ocr/research"
asta ocr "$WORKSPACE" \
  --pdfs research-paper.pdf \
  --server https://api.deepinfra.com/v1/openai \
  --api_key "$DEEPINFRA_API_KEY" \
  --markdown

# 2. Index in asta documents
MARKDOWN_FILE="$WORKSPACE/markdown/research-paper.md"
asta documents add "file://${MARKDOWN_FILE}" \
  --name="Research Paper (OCR)" \
  --summary="Extracted via olmOCR" \
  --tags="ocr,extracted,research"
```

## API Provider Configuration

### DeepInfra

```bash
export DEEPINFRA_API_KEY="your-key"
SERVER="https://api.deepinfra.com/v1/openai"

asta ocr ~/workspace/output \
  --pdfs document.pdf \
  --server "$SERVER" \
  --api_key "$DEEPINFRA_API_KEY" \
  --markdown
```

### Cirrascale (Cheapest Option)

```bash
export CIRRASCALE_API_KEY="your-key"
SERVER="https://api.cirrascale.com/v1"

asta ocr ~/workspace/output \
  --pdfs document.pdf \
  --server "$SERVER" \
  --api_key "$CIRRASCALE_API_KEY" \
  --markdown
```

### Parasail (Enterprise)

```bash
export PARASAIL_API_KEY="your-key"
SERVER="https://api.parasail.io/v1"

asta ocr ~/workspace/output \
  --pdfs document.pdf \
  --server "$SERVER" \
  --api_key "$PARASAIL_API_KEY" \
  --markdown
```

## Output Structure

After extraction, the workspace directory contains:

```
workspace/
├── markdown/           # Markdown output (if --markdown used)
│   └── document.md
├── output/            # Raw JSON output
│   └── document.json
└── work_queue/        # Internal work tracking
```

The extracted text is saved as markdown, preserving:
- Document structure
- Headings and formatting
- Tables (as markdown tables)
- Lists and emphasis

## Advanced Options

### Control Parallelism

```bash
# Process with 50 parallel workers (faster for large batches)
asta ocr ~/workspace/output \
  --pdfs papers/*.pdf \
  --server "$API_SERVER" \
  --api_key "$API_KEY" \
  --workers 50 \
  --markdown
```

### Filter Documents

```bash
# Apply filters to skip non-English or form-like documents
asta ocr ~/workspace/output \
  --pdfs documents/*.pdf \
  --server "$API_SERVER" \
  --api_key "$API_KEY" \
  --apply_filter \
  --markdown
```

### Workspace Statistics

```bash
# View statistics about a workspace
asta ocr ~/workspace/output --stats
```

## Local GPU Mode (Advanced)

If you have a GPU with 12GB+ VRAM, you can run locally:

```bash
# Install with GPU dependencies
uv tool install --from /Users/rodneyk/workspace/olmocr --with gpu olmocr

# Run locally (no --server or --api_key needed)
asta ocr ~/workspace/output \
  --pdfs document.pdf \
  --markdown
```

**Note:** Local mode requires substantial disk space (~30GB) and GPU memory.

## Performance and Cost

### API Mode
- **Speed**: ~10-20 seconds per page (cloud GPU)
- **Cost**: $0.07-0.10 per 1M tokens
- **No setup**: Works immediately with API key

### Local GPU Mode
- **Speed**: ~10-20 seconds per page (RTX 4090)
- **Cost**: Free after installation
- **Requirements**: 12GB+ GPU VRAM, 30GB disk space

## Troubleshooting

### "API key required"

Make sure you provide both `--server` and `--api_key`:

```bash
asta ocr workspace --pdfs file.pdf \
  --server https://api.deepinfra.com/v1/openai \
  --api_key "$YOUR_API_KEY" \
  --markdown
```

### "workspace is required"

The first argument must be a workspace directory:

```bash
# ✓ Correct
asta ocr ~/workspace/output --pdfs file.pdf ...

# ✗ Wrong (missing workspace)
asta ocr --pdfs file.pdf ...
```

### "Connection failed"

1. Check API key is correct
2. Verify internet connection
3. Try a different provider

### "No output files"

Check the output directories:
- Markdown: `<workspace>/markdown/`
- JSON: `<workspace>/output/`

## When to Use This Skill

✅ Use olmOCR when:
- User wants to extract text from a PDF
- User mentions "OCR", "read PDF", "extract from document"
- Processing scanned or image-based PDFs
- Dealing with complex layouts (tables, multi-column, equations)
- Need high-quality text extraction for downstream tasks

❌ Don't use when:
- PDF already contains selectable text (use simpler tools)
- User wants to process images directly (olmOCR is PDF-specific)
- User needs real-time/streaming extraction

## Additional Resources

- **olmOCR GitHub**: https://github.com/allenai/olmOCR
- **Provider Signup**:
  - DeepInfra: https://deepinfra.com
  - Cirrascale: Contact AI2
  - Parasail: https://parasail.io
