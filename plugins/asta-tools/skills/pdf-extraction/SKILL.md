---
name: pdf-extraction
description: Extract text from PDFs using the Asta remote OCR API. Use when the user asks to "extract text from PDF", "OCR a document", "read a PDF", or needs to process scanned documents.
allowed-tools: Bash(asta pdf-extraction *) Read(.asta/documents/*) Write(.asta/documents/*) Read(*/markdown/*) Bash(mv *) Bash(cp *)
---

# PDF Text Extraction

Extract text from a local PDF with the Asta remote OCR API. The command returns
markdown that preserves document structure, headings, formatting, tables, lists,
and emphasis.

## Quick Start

```bash
# Print extracted markdown to stdout
asta pdf-extraction remote paper.pdf

# Save extracted markdown to a file
asta pdf-extraction remote paper.pdf -o paper.md

# Extract the first 50 pages
asta pdf-extraction remote paper.pdf \
  --start-page 0 \
  --max-pages 50 \
  -o paper-part-1.md

# Extract pages 50-99
asta pdf-extraction remote paper.pdf \
  --start-page 50 \
  --max-pages 50 \
  -o paper-part-2.md

# Extract embedded images next to the markdown file
asta pdf-extraction remote paper.pdf -o output/paper.md --images
```

## Arguments

- `<pdf>`: local PDF path (required; the file must exist and be readable)
- `-o / --output`: markdown output path (default: stdout)
- `--start-page`: first page to process, using zero-based page numbering
  (default: `0`)
- `--max-pages`: maximum number of pages to process (default: `50`)
- `--images / --no-images`: save embedded images alongside the markdown
  (default: `--no-images`)

The command requires an authenticated Asta session.

## Procedure

### 1. Confirm the input and output

Identify the local PDF and where the user wants the markdown saved. Prefer an
explicit `-o` path so the result is available for later work. The command
creates missing parent directories for the output file.

### 2. Choose a page range

For PDFs of 50 pages or fewer, use the defaults:

```bash
asta pdf-extraction remote document.pdf -o document.md
```

For longer PDFs, process consecutive ranges in separate commands. Page numbers
are zero-based, so the second 50-page range begins at page `50`:

```bash
asta pdf-extraction remote document.pdf \
  --start-page 0 --max-pages 50 -o document-part-001.md
asta pdf-extraction remote document.pdf \
  --start-page 50 --max-pages 50 -o document-part-002.md
asta pdf-extraction remote document.pdf \
  --start-page 100 --max-pages 50 -o document-part-003.md
```

Keep the part numbers zero-padded so the files sort in page order.

### 3. Extract images when needed

Use `--images` when figures, diagrams, or other embedded images are important:

```bash
asta pdf-extraction remote document.pdf \
  -o extracted/document.md \
  --images
```

The images are saved in the output file's directory and referenced by filename
in the markdown. Always provide `-o` with `--images`; without it, images are
written to the current directory.

### 4. Verify the result

After extraction, check that:

- The output file exists and is not empty.
- The first and last requested pages are present.
- Headings, tables, equations, and multi-column text are readable.
- Image references resolve when `--images` was requested.

If the document was processed in parts, retain the original PDF and page ranges
with the extracted files so their order and provenance remain clear.

## Common Workflows

### Extract a scanned PDF

```bash
asta pdf-extraction remote scanned-document.pdf \
  -o extracted/scanned-document.md
```

### Extract only a selected range

To extract pages 21-30 as displayed in a PDF viewer, start at zero-based page
`20` and request 10 pages:

```bash
asta pdf-extraction remote report.pdf \
  --start-page 20 \
  --max-pages 10 \
  -o report-pages-21-30.md
```

### Extract text for an Asta document index

Save the markdown under the user's dataset or document directory, then use the
`asta-documents` or `local-paper-index` skill to index it. Preserve a link to
the source PDF in the index metadata when possible.

## Troubleshooting

### Authentication error

Confirm that the user is logged in to Asta, then retry the same command.

### Remote OCR API error

The command reports the HTTP status and response from the service. Verify the
network connection and retry. If a large request repeatedly fails, reduce
`--max-pages` and process smaller page ranges.

### Empty or incomplete output

- Confirm that `--start-page` is within the document.
- Check whether the requested range extends beyond the final page.
- Retry with fewer pages.
- For image-only or unusually complex pages, inspect the corresponding page in
  the source PDF before accepting the extraction.

### Images were written to the wrong directory

Run the command with both `--images` and an explicit `-o` path. Images are saved
next to the output file; if no output file is provided, they are saved in the
current directory.

## When to Use This Skill

Use PDF extraction when:

- The user wants text or markdown extracted from a PDF.
- The PDF is scanned or contains image-based text that requires optical
  character recognition (OCR).
- The document has tables, equations, multiple columns, or complex formatting.
- Extracted text is needed for indexing or downstream analysis.

Do not use it when:

- The input is an image rather than a PDF.
- The user only needs paper metadata or short searchable snippets.
- The user needs real-time or streaming extraction.
