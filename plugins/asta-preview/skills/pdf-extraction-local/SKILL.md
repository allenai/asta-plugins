---
name: PDF Text Extraction (Local/PyMuPDF)
description: This skill should be used when the user asks to "extract text from PDF locally", "convert PDF to text without a server", "read PDF using PyMuPDF", "parse PDF offline", or needs to process PDF documents locally without requiring a remote OCR service.
allowed-tools:
  - Bash(asta pdf-extraction-local *)
  - Read
  - Write
metadata:
  internal: true
---

# PDF Text Extraction (Local/PyMuPDF)

Extract structured text from PDF files locally using PyMuPDF Layout, which combines heuristics with machine learning for improved accuracy. No server or authentication required — runs entirely on your machine.

## Installation

Install with the `pdf-local` extra to get PyMuPDF dependencies:
```bash
uv tool install "asta[pdf-local]" --from git+ssh://git@github.com/allenai/asta-plugins.git
```

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/)

Verify installation with:
```bash
asta pdf-extraction-local --help
```

## Usage

### Single PDF Extraction

Extract to markdown (default, best for preserving structure):
```bash
asta pdf-extraction-local to-text document.pdf
```

Extract to JSON (structured output):
```bash
asta pdf-extraction-local to-text document.pdf --format json
```

Extract to plain text:
```bash
asta pdf-extraction-local to-text document.pdf --format text
```

### Batch Processing Multiple PDFs

Process multiple PDFs in parallel for improved performance:
```bash
# Extract all PDFs in current directory
asta pdf-extraction-local batch-extract *.pdf -o ./extracted

# Extract specific PDFs
asta pdf-extraction-local batch-extract file1.pdf file2.pdf file3.pdf -o ./output

# Use JSON format
asta pdf-extraction-local batch-extract *.pdf -o ./output --format json

# Control number of worker processes
asta pdf-extraction-local batch-extract *.pdf -o ./output --workers 4
```

### Save to File

```bash
asta pdf-extraction-local to-text document.pdf -o output.md
asta pdf-extraction-local to-text document.pdf --format json -o output.json
```

### Extract Specific Pages

```bash
# Page range
asta pdf-extraction-local to-text document.pdf --pages 1-5

# Specific pages
asta pdf-extraction-local to-text document.pdf --pages 1,3,5,10
```

### Control Output Format

```bash
# Without page chunks (single continuous text)
asta pdf-extraction-local to-text document.pdf --no-page-chunks
```

## Output Formats

### Markdown (Default)
- Preserves document structure (headings, lists, tables)
- Best for readability and further processing
- Can be chunked by page or continuous

### JSON
- Structured data with metadata
- Always uses page chunks
- Suitable for programmatic processing

### Text
- Plain text without formatting
- Simplest output
- Good for basic text analysis

## Common Workflows

### Extract and Index
```bash
# Extract PDF to markdown
asta pdf-extraction-local to-text research_paper.pdf -o paper.md

# Index in document database
asta documents add file://paper.md --name="Research Paper" --summary="..."
```

### Batch Processing with Multiprocessing
```bash
# Faster: Use built-in batch processing (2x+ speedup)
asta pdf-extraction-local batch-extract *.pdf -o ./extracted

# Alternative: Shell loop (slower, sequential)
for pdf in *.pdf; do
  asta pdf-extraction-local to-text "$pdf" -o "${pdf%.pdf}.md"
done
```

### Extract for Analysis
```bash
# Extract to JSON for structured analysis
asta pdf-extraction-local to-text document.pdf --format json | jq '.content'
```

## Tips

- Use markdown format for best structure preservation
- Use page chunks when working with large documents
- Use JSON format when you need structured data for processing
- Specify page ranges to extract only relevant sections
- Use `batch-extract` for processing 10+ PDFs (2x or better speedup)
- The batch command automatically uses all CPU cores for parallel processing
- Use this command when you don't have access to the olmOCR server or prefer local processing

## Supported Features

- Multi-column layouts
- Tables and lists
- Figure captions
- Mathematical equations (extracted as text)
- Complex document structures
