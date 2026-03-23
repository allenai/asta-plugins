"""Extract text from PDF files using PyMuPDF Layout"""

import json
from pathlib import Path

import click
import pymupdf

# Import order is critical - pymupdf.layout must be imported first
import pymupdf.layout  # noqa: F401
import pymupdf4llm


@click.command(name="to-text")
@click.argument(
    "pdf_path", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json", "text"]),
    default="markdown",
    help="Output format for extracted text",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output file path (default: stdout)",
)
@click.option(
    "--page-chunks/--no-page-chunks",
    default=True,
    help="Split output into page chunks (markdown format only)",
)
@click.option(
    "--pages",
    help="Page range to extract (e.g., '1-5' or '1,3,5')",
)
def to_text(
    pdf_path: Path,
    output_format: str,
    output: Path | None,
    page_chunks: bool,
    pages: str | None,
):
    """Extract text from PDF files using PyMuPDF Layout.

    Extracts structured text from PDF files with improved layout detection.
    Supports markdown, JSON, and plain text output formats.

    Examples:

        # Extract to markdown (default)
        asta pdf-extraction-local to-text document.pdf

        # Extract to JSON with output file
        asta pdf-extraction-local to-text document.pdf --format json -o output.json

        # Extract specific pages to markdown
        asta pdf-extraction-local to-text document.pdf --pages 1-5

        # Extract without page chunks
        asta pdf-extraction-local to-text document.pdf --no-page-chunks
    """
    try:
        # Parse page range if provided
        page_list = None
        if pages:
            page_list = _parse_page_range(pages)

        # Open the PDF
        doc = pymupdf.open(pdf_path)

        # Extract based on format
        if output_format == "markdown":
            result_data = pymupdf4llm.to_markdown(
                doc,
                pages=page_list,
                page_chunks=page_chunks,
            )
            # Convert to string if it's a list (page chunks mode)
            if isinstance(result_data, list):
                # Each chunk may be a dict with 'text' key or a string
                chunks = []
                for chunk in result_data:
                    if isinstance(chunk, dict):
                        chunks.append(chunk.get("text", str(chunk)))
                    else:
                        chunks.append(str(chunk))
                result = "\n\n".join(chunks)
            else:
                result = result_data
        elif output_format == "json":
            result_data = pymupdf4llm.to_markdown(
                doc,
                pages=page_list,
                page_chunks=True,  # Always use chunks for JSON
            )
            # Convert to JSON format
            if isinstance(result_data, list):
                result = json.dumps(result_data, indent=2)
            else:
                result = json.dumps(
                    {"content": result_data, "metadata": {"source": str(pdf_path)}},
                    indent=2,
                )
        else:  # text
            result = []
            for page_num in page_list if page_list else range(len(doc)):
                page = doc[page_num]
                result.append(page.get_text())
            result = "\n\n".join(result)

        # Output result
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result)
            click.echo(f"Text extracted to: {output}", err=True)
        else:
            click.echo(result)

        doc.close()

    except Exception as e:
        raise click.ClickException(f"Failed to extract text from PDF: {e}")


def _parse_page_range(page_spec: str) -> list[int]:
    """Parse page specification like '1-5' or '1,3,5' into list of 0-based page indices."""
    pages = []
    for part in page_spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            # Convert to 0-based indexing
            pages.extend(range(int(start) - 1, int(end)))
        else:
            # Convert to 0-based indexing
            pages.append(int(part) - 1)
    return pages
