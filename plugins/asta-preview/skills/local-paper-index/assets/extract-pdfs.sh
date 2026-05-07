#!/usr/bin/env bash
# Extract PDFs to markdown using asta pdf-extraction remote.
#
# Usage:
#   ./extract-pdfs.sh [--images] <pdf-dir-or-glob> <output-markdown-dir>
#
# Skips PDFs whose markdown output already exists (supports resuming).
# For PDFs >50 pages, extracts in 50-page increments and concatenates.
#
# With --images, each PDF gets its own subdirectory under the output dir
# (e.g. output/paper1/paper1.md + images) so that images from different
# PDFs don't collide. Without --images, markdown files are written flat.
set -euo pipefail

# Parse optional --images flag
IMAGES=false
if [ "${1:-}" = "--images" ]; then
  IMAGES=true
  shift
fi

if [ $# -lt 2 ]; then
  echo "Usage: $0 [--images] <pdf-dir-or-glob> <output-markdown-dir>" >&2
  exit 1
fi

PDF_SOURCE="$1"
MARKDOWN_DIR="$2"
mkdir -p "$MARKDOWN_DIR"

# Build the extra flags for asta pdf-extraction remote
EXTRA_FLAGS=()
if [ "$IMAGES" = true ]; then
  EXTRA_FLAGS+=(--images)
fi

# Collect PDF paths
PDF_FILES=()
if [ -d "$PDF_SOURCE" ]; then
  while IFS= read -r -d '' f; do
    PDF_FILES+=("$f")
  done < <(find "$PDF_SOURCE" -name "*.pdf" -type f -print0 | sort -z)
else
  # Treat as glob (already expanded by shell) or single file
  for f in $PDF_SOURCE; do
    [ -f "$f" ] && PDF_FILES+=("$f")
  done
fi

TOTAL=${#PDF_FILES[@]}
if [ "$TOTAL" -eq 0 ]; then
  echo "No PDF files found in: $PDF_SOURCE" >&2
  exit 1
fi

echo "Found $TOTAL PDF(s) to extract"
echo "Output directory: $MARKDOWN_DIR"
if [ "$IMAGES" = true ]; then
  echo "Image extraction: enabled (per-PDF subdirectories)"
else
  echo "Image extraction: disabled (flat markdown files)"
fi
echo

EXTRACTED=0
SKIPPED=0

for pdf in "${PDF_FILES[@]}"; do
  BASENAME=$(basename "$pdf" .pdf)

  # With --images: output to a per-PDF subdirectory so images don't collide.
  # Without --images: output flat markdown files directly in MARKDOWN_DIR.
  if [ "$IMAGES" = true ]; then
    OUTPUT_DIR="$MARKDOWN_DIR/$BASENAME"
    OUTPUT_FILE="$OUTPUT_DIR/${BASENAME}.md"
    mkdir -p "$OUTPUT_DIR"
  else
    OUTPUT_FILE="$MARKDOWN_DIR/${BASENAME}.md"
  fi

  if [ -f "$OUTPUT_FILE" ] && [ -s "$OUTPUT_FILE" ]; then
    echo "  [skip] $BASENAME (already extracted)"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  echo "  [extract] $BASENAME"

  # Try single extraction first (works for <=50 pages)
  if asta pdf-extraction remote "$pdf" -o "$OUTPUT_FILE" "${EXTRA_FLAGS[@]}" 2>/dev/null; then
    EXTRACTED=$((EXTRACTED + 1))
    continue
  fi

  # For large PDFs: extract in 50-page increments
  echo "    Trying multi-part extraction for large PDF..."
  PAGE=0
  PARTS=()
  while true; do
    PART_FILE="${MARKDOWN_DIR}/${BASENAME}_part${PAGE}.md"
    if asta pdf-extraction remote "$pdf" --start-page "$PAGE" --max-pages 50 -o "$PART_FILE" "${EXTRA_FLAGS[@]}" 2>/dev/null; then
      if [ -s "$PART_FILE" ]; then
        PARTS+=("$PART_FILE")
        PAGE=$((PAGE + 50))
      else
        rm -f "$PART_FILE"
        break
      fi
    else
      rm -f "$PART_FILE"
      break
    fi
  done

  if [ ${#PARTS[@]} -gt 0 ]; then
    cat "${PARTS[@]}" > "$OUTPUT_FILE"
    rm -f "${PARTS[@]}"
    EXTRACTED=$((EXTRACTED + 1))
  else
    echo "    WARNING: Failed to extract $BASENAME" >&2
  fi
done

echo
echo "Done: $EXTRACTED extracted, $SKIPPED skipped (already existed)"
