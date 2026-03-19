---
name: PDF Text Extraction
description: Extract text from PDFs using olmOCR. Use when user asks to "extract text from PDF", "OCR a document", "read a PDF", or needs to process scanned documents.
allowed-tools:
  - Bash(asta pdf-extraction *)
  - Bash(olmocr *)
  - Read(.asta/documents/*)
  - Read(*/markdown/*)
  - Write(.asta/documents/*)
  - Bash(mv *)
  - Bash(cp *)
---

# PDF Text Extraction

Extract high-quality text from PDFs using the [olmOCR](https://github.com/allenai/olmOCR) tool. This skill uses the olmocr CLI for cloud-based OCR processing.

## Quick Start

### Extract Text from PDF

The olmocr CLI will auto-install on first use. Basic usage:

```bash
# Extract text from a PDF using a temporary workspace
TEMP_WORKSPACE=$(mktemp -d)
asta pdf-extraction "$TEMP_WORKSPACE" \
  --pdfs document.pdf \
  --markdown

# Output will be in $TEMP_WORKSPACE/markdown/document.md
```

### Understanding olmocr CLI

The `asta pdf-extraction` command is a passthrough to `olmocr` with this syntax:

```bash
olmocr <workspace> [OPTIONS]
```

**Key arguments:**
- `<workspace>` - Output directory (required, positional argument)
- `--pdfs` - PDF file(s) to process
- `--markdown` - Generate markdown output (recommended)
- `--workers` - Parallel workers (default: 20)

## Workspace Best Practices

### Use Temporary Workspace, Move Final Output

**Recommended workflow:**

```bash
# 1. Create temporary workspace (not in .asta/documents)
TEMP_WORKSPACE=$(mktemp -d)

# 2. Extract text
asta pdf-extraction "$TEMP_WORKSPACE" \
  --pdfs research-paper.pdf \
  --markdown

# 3. Move final output to permanent location
mkdir -p ~/.asta/documents/research
mv "$TEMP_WORKSPACE/markdown/research-paper.md" ~/.asta/documents/research/

# 4. Clean up temporary files
rm -rf "$TEMP_WORKSPACE"
```

**Why use a temporary workspace?**
- olmOCR creates several intermediate files (JSON, work queues, etc.)
- You typically only need the final markdown output
- Keeping .asta/documents clean with only final outputs
- Easy cleanup of temporary files

**Where to store final outputs:**
- `~/.asta/documents/` - For indexing with `asta documents`
- User's project directory - For project-specific documents
- Any location convenient for the user's workflow

## Common Workflows

### Extract Single PDF

```bash
# Create temporary workspace and extract
TEMP_WORKSPACE=$(mktemp -d)
asta pdf-extraction "$TEMP_WORKSPACE" \
  --pdfs paper.pdf \
  --markdown

# Review the extracted text
cat "$TEMP_WORKSPACE/markdown/paper.md"

# Move to permanent location
mkdir -p ~/.asta/documents/papers
mv "$TEMP_WORKSPACE/markdown/paper.md" ~/.asta/documents/papers/

# Clean up
rm -rf "$TEMP_WORKSPACE"
```

### Extract Multiple PDFs

```bash
# Process all PDFs in a directory
TEMP_WORKSPACE=$(mktemp -d)
asta pdf-extraction "$TEMP_WORKSPACE" \
  --pdfs papers/*.pdf \
  --markdown \
  --workers 10

# Move all extracted markdown files
mkdir -p ~/.asta/documents/batch
mv "$TEMP_WORKSPACE/markdown/"*.md ~/.asta/documents/batch/

# Clean up
rm -rf "$TEMP_WORKSPACE"
```

### Extract and Index in Documents

```bash
# 1. Extract text to temporary workspace
TEMP_WORKSPACE=$(mktemp -d)
asta pdf-extraction "$TEMP_WORKSPACE" \
  --pdfs research-paper.pdf \
  --markdown

# 2. Move to documents directory
mkdir -p ~/.asta/documents/research
FINAL_PATH=~/.asta/documents/research/research-paper.md
mv "$TEMP_WORKSPACE/markdown/research-paper.md" "$FINAL_PATH"

# 3. Index in asta documents
asta documents add "file://${FINAL_PATH}" \
  --name="Research Paper (OCR)" \
  --summary="Extracted via olmOCR" \
  --tags="ocr,extracted,research"

# 4. Clean up temporary workspace
rm -rf "$TEMP_WORKSPACE"
```

## S3 Support

olmOCR supports reading PDFs from S3 and using S3 as a workspace.

### Read PDFs from S3

```bash
# Extract PDF stored in S3
TEMP_WORKSPACE=$(mktemp -d)
asta pdf-extraction "$TEMP_WORKSPACE" \
  --pdfs s3://my-bucket/documents/paper.pdf \
  --markdown

# Output will be in local workspace
cat "$TEMP_WORKSPACE/markdown/paper.md"
```

### Use S3 as Workspace

```bash
# Use S3 bucket as workspace (requires AWS credentials)
asta pdf-extraction s3://my-bucket/ocr-workspace \
  --pdfs document.pdf \
  --markdown

# Output will be in s3://my-bucket/ocr-workspace/markdown/document.md
```

**S3 Configuration:**
- Requires AWS credentials configured (via `~/.aws/credentials` or environment variables)
- Uses standard boto3 credential resolution
- Can mix local and S3 paths (e.g., S3 PDFs to local workspace, or vice versa)

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
TEMP_WORKSPACE=$(mktemp -d)
asta pdf-extraction "$TEMP_WORKSPACE" \
  --pdfs papers/*.pdf \
  --workers 50 \
  --markdown
```

### Filter Documents

```bash
# Apply filters to skip non-English or form-like documents
TEMP_WORKSPACE=$(mktemp -d)
asta pdf-extraction "$TEMP_WORKSPACE" \
  --pdfs documents/*.pdf \
  --apply_filter \
  --markdown
```

### Workspace Statistics

```bash
# View statistics about a workspace
asta pdf-extraction ~/workspace/output --stats
```

## Performance and Cost

- **Speed**: ~10-20 seconds per page (cloud GPU)
- **Cost**: ~$0.001-0.01 per typical PDF (10-50 pages)
- **No setup**: Works immediately, API configuration handled automatically

## Troubleshooting

### "workspace is required"

The first argument must be a workspace directory:

```bash
# ✓ Correct
asta pdf-extraction ~/workspace/output --pdfs file.pdf ...

# ✗ Wrong (missing workspace)
asta pdf-extraction --pdfs file.pdf ...
```

### "Connection failed"

1. Verify internet connection
2. Check if the service is currently available

### "No output files"

Check the output directories:
- Markdown: `<workspace>/markdown/`
- JSON: `<workspace>/output/`

### S3 Access Issues

1. Verify AWS credentials are configured
2. Check bucket permissions (read for --pdfs, read/write for workspace)
3. Ensure IAM user/role has s3:GetObject, s3:PutObject, s3:ListBucket permissions

## When to Use This Skill

✅ Use PDF extraction when:
- User wants to extract text from a PDF
- User mentions "OCR", "read PDF", "extract from document"
- Processing scanned or image-based PDFs
- Dealing with complex layouts (tables, multi-column, equations)
- Need high-quality text extraction for downstream tasks

❌ Don't use when:
- User wants to process images directly (olmOCR is PDF-specific)
- User needs real-time/streaming extraction

## Additional Resources

- **olmOCR GitHub**: https://github.com/allenai/olmOCR
