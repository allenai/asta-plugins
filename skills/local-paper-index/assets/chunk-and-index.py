#!/usr/bin/env python3
"""Chunk markdown files and write an asta-documents YAML index.

Writes the index YAML directly (no per-chunk CLI calls), following the same
schema as asta-documents: version 1.0, documents list with uuid/name/url/
summary/tags/extra/created_at/modified_at.

Usage:
    python3 chunk-and-index.py <collection-name> <markdown-dir> --index-path <path>

The input is always a directory of markdown files. Those markdown files may be
extraction output from PDFs (the default `--source-ext pdf` case) OR raw,
authored markdown that was never a PDF (`--source-ext md`, or any extension).
Use the latter to index a corpus of `.md` documents directly, skipping the
PDF-extraction step entirely. `--source-ext` only controls the synthesized
source filename and the secondary index tag; chunking is identical.

The --index-path is required. The script computes relative URLs for markdown
files relative to the directory containing the index file. Files outside that
directory get absolute file:// URLs.

The markdown-dir can contain either:
  - Per-PDF subdirectories (typical extraction output):
      markdown/paper1/paper1.md, markdown/paper1/img-0.jpeg, ...
  - Flat .md files:
      markdown/paper1.md, markdown/paper2.md, ...

The source PDF name is derived from the subdirectory name (if nested) or
the .md file stem (if flat).

Each PDF is represented by multiple documents in the index. They share
PDF-level metadata (source_pdf, collection) with per-chunk identifiers
(chunk_index, total_chunks).
"""

import argparse
import secrets
import string
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

CHUNK_SIZE = 2000


def generate_uuid(length=10):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[tuple[str, int]]:
    """Split text into chunks of approximately `size` characters.

    Tries to break at paragraph or sentence boundaries when possible.
    Returns a list of (chunk_text, offset) tuples where offset is the
    character position within the original text.
    """
    if len(text) <= size:
        return [(text, 0)]

    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        if end >= len(text):
            chunks.append((text[start:], start))
            break

        segment = text[start:end]
        para_break = segment.rfind("\n\n")
        if para_break > size * 0.5:
            end = start + para_break + 2
        else:
            sent_break = max(segment.rfind(". "), segment.rfind(".\n"))
            if sent_break > size * 0.3:
                end = start + sent_break + 2
            else:
                word_break = segment.rfind(" ")
                if word_break > size * 0.5:
                    end = start + word_break + 1

        chunks.append((text[start:end], start))
        start = end

    return chunks


def make_url(md_file: Path, index_dir: Path) -> str:
    """Compute a URL for a markdown file, relative to the index directory.

    If the file is under the index directory, returns a relative path
    (portable, git-friendly). Otherwise returns an absolute file:// URL.
    """
    resolved = md_file.resolve()
    try:
        rel = resolved.relative_to(index_dir)
        return str(rel)
    except ValueError:
        return f"file://{resolved}"


def load_existing_index(index_path: Path) -> dict:
    """Load an existing index file, or return an empty index structure."""
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "documents" in data:
            return data
    return {"version": "1.0", "documents": []}


def find_existing_sources(documents: list[dict], collection: str) -> set[str]:
    """Find source filenames already in the index for this collection.

    Reads the canonical ``source_file`` key and falls back to the legacy
    ``source_pdf`` key so indexes written by older runs stay resumable.
    """
    seen = set()
    for doc in documents:
        extra = doc.get("extra", {})
        if extra.get("collection") == collection:
            source = extra.get("source_file") or extra.get("source_pdf", "")
            if source:
                seen.add(source)
    return seen


def main():
    parser = argparse.ArgumentParser(
        description="Chunk markdown files and write asta-documents YAML index"
    )
    parser.add_argument(
        "collection", help="Collection name (used as tag and in metadata)"
    )
    parser.add_argument(
        "markdown_dir",
        help="Directory containing PDF extraction output (subdirectories with .md + images, or flat .md files)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help="Chunk size in characters (default: 2000)",
    )
    parser.add_argument(
        "--source-ext",
        default="pdf",
        help=(
            "Extension of the original source documents, used to synthesize the "
            "stored source filename and the secondary index tag '<ext>-index'. "
            "Defaults to 'pdf' for PDF-extraction output; pass 'md' (or 'txt', "
            "etc.) to index a corpus of raw markdown/text documents directly."
        ),
    )
    parser.add_argument(
        "--index-path",
        required=True,
        help="Path to index YAML file (e.g. /path/to/dataset/index.yaml)",
    )
    args = parser.parse_args()

    md_dir = Path(args.markdown_dir)
    index_path = Path(args.index_path)
    chunk_size = args.chunk_size
    collection = args.collection
    source_ext = args.source_ext.lstrip(".")
    index_tag = f"{source_ext}-index"

    if not md_dir.exists():
        print(f"Error: markdown directory not found: {md_dir}", file=sys.stderr)
        sys.exit(1)

    # Find .md files: supports both per-PDF subdirectories (with images) and
    # flat .md files directly in markdown_dir.
    md_files = sorted(md_dir.rglob("*.md"))
    if not md_files:
        print(f"Error: no .md files found in {md_dir}", file=sys.stderr)
        sys.exit(1)

    index_dir = index_path.resolve().parent
    print(f"Index directory: {index_dir}")
    try:
        md_dir.resolve().relative_to(index_dir)
    except ValueError:
        print(
            f"WARNING: markdown dir {md_dir} is outside index directory {index_dir}; "
            "URLs will be absolute file:// paths",
            file=sys.stderr,
        )

    # Load existing index (preserves previously indexed documents)
    index_data = load_existing_index(index_path)
    existing_sources = find_existing_sources(index_data["documents"], collection)

    now = datetime.now(UTC).isoformat()
    new_docs = 0
    docs_processed = 0
    docs_skipped_empty = 0
    docs_skipped_existing = 0

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        # Derive the source name: if the .md is in a subdirectory of markdown_dir,
        # use the subdirectory name (e.g. markdown/paper1/paper1.md -> paper1.<ext>).
        # If flat in markdown_dir, use the file stem.
        if md_file.parent != md_dir:
            basename = md_file.parent.name
        else:
            basename = md_file.stem
        source_file = f"{basename}.{source_ext}"

        if not text.strip():
            print(f"  [skip] {basename} (empty)")
            docs_skipped_empty += 1
            continue

        if source_file in existing_sources:
            print(f"  [skip] {basename} (already indexed)")
            docs_skipped_existing += 1
            continue

        url = make_url(md_file, index_dir)
        file_size = len(text)
        chunks = chunk_text(text, chunk_size)

        for i, (chunk, offset) in enumerate(chunks, 1):
            extra = {
                "source_file": source_file,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "chunk_chars": len(chunk),
                "chunk_offset": offset,
                "file_chars": file_size,
                "collection": collection,
            }
            # Preserve the legacy key for PDF collections so existing consumers
            # and indexes that filter on `source_pdf` keep working unchanged.
            if source_ext == "pdf":
                extra["source_pdf"] = source_file
            doc_entry = {
                "uuid": generate_uuid(),
                "name": f"{basename} [chunk {i}/{len(chunks)}]",
                "mime_type": "text/markdown",
                "url": url,
                "summary": chunk,
                "tags": [collection, index_tag],
                "created_at": now,
                "modified_at": now,
                "extra": extra,
            }
            index_data["documents"].append(doc_entry)
            new_docs += 1

        docs_processed += 1
        print(f"  [index] {basename} ({len(chunks)} chunks) -> {url}")

    # Write index
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        yaml.dump(
            index_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    print()
    print(f"Sources processed:      {docs_processed}")
    print(f"Sources skipped (empty):{docs_skipped_empty}")
    print(f"Sources skipped (exists):{docs_skipped_existing}")
    print(f"New documents added:    {new_docs}")
    print(f"Total documents in idx: {len(index_data['documents'])}")
    print(f"Index written to:       {index_path}")


if __name__ == "__main__":
    main()
