"""Batch extract text from multiple PDF files using multiprocessing"""

from multiprocessing import Pool, cpu_count
from pathlib import Path

import click

# Import order is critical - pymupdf.layout must be imported first
import pymupdf
import pymupdf.layout  # noqa: F401
import pymupdf4llm


def _process_single_pdf(args):
    """Process a single PDF file. Used by multiprocessing pool."""
    pdf_path, output_dir, output_format, page_chunks = args

    try:
        # Open the PDF
        doc = pymupdf.open(pdf_path)

        # Extract based on format
        if output_format == "markdown":
            result_data = pymupdf4llm.to_markdown(
                doc,
                page_chunks=page_chunks,
            )
            # Convert to string if it's a list (page chunks mode)
            if isinstance(result_data, list):
                chunks = []
                for chunk in result_data:
                    if isinstance(chunk, dict):
                        chunks.append(chunk.get("text", str(chunk)))
                    else:
                        chunks.append(str(chunk))
                result = "\n\n".join(chunks)
            else:
                result = result_data
            extension = ".md"
        elif output_format == "json":
            import json

            result_data = pymupdf4llm.to_markdown(
                doc,
                page_chunks=True,  # Always use chunks for JSON
            )
            if isinstance(result_data, list):
                result = json.dumps(result_data, indent=2)
            else:
                result = json.dumps(
                    {"content": result_data, "metadata": {"source": str(pdf_path)}},
                    indent=2,
                )
            extension = ".json"
        else:  # text
            result = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                result.append(page.get_text())
            result = "\n\n".join(result)
            extension = ".txt"

        doc.close()

        # Determine output path
        output_path = output_dir / f"{Path(pdf_path).stem}{extension}"
        output_path.write_text(result)

        return {"success": True, "input": str(pdf_path), "output": str(output_path)}

    except Exception as e:
        return {"success": False, "input": str(pdf_path), "error": str(e)}


@click.command(name="batch-extract")
@click.argument("pdf_files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Output directory for extracted files",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json", "text"]),
    default="markdown",
    help="Output format for extracted text",
)
@click.option(
    "--page-chunks/--no-page-chunks",
    default=True,
    help="Split output into page chunks (markdown format only)",
)
@click.option(
    "--workers",
    type=int,
    default=None,
    help="Number of worker processes (default: CPU count)",
)
def batch_extract(pdf_files, output_dir, output_format, page_chunks, workers):
    """Extract text from multiple PDF files in parallel.

    Processes multiple PDFs using multiprocessing for improved performance.
    Each PDF is processed independently and saved to the output directory.

    Examples:

        # Extract all PDFs in current directory
        asta pdf batch-extract *.pdf -o ./extracted

        # Extract specific PDFs to JSON
        asta pdf batch-extract file1.pdf file2.pdf -o ./output --format json

        # Control worker processes
        asta pdf batch-extract *.pdf -o ./output --workers 4
    """
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine number of workers
    if workers is None:
        workers = min(cpu_count(), len(pdf_files))
    else:
        workers = min(workers, len(pdf_files))

    click.echo(f"Processing {len(pdf_files)} PDFs with {workers} workers...", err=True)

    # Prepare arguments for multiprocessing
    args = [
        (str(pdf_file), output_dir, output_format, page_chunks)
        for pdf_file in pdf_files
    ]

    # Process PDFs in parallel
    with Pool(workers) as pool:
        results = pool.map(_process_single_pdf, args)

    # Report results
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    click.echo(f"\n✓ Successfully processed {len(successful)} PDFs", err=True)
    if failed:
        click.echo(f"✗ Failed to process {len(failed)} PDFs:", err=True)
        for result in failed:
            click.echo(f"  - {result['input']}: {result['error']}", err=True)

    # Exit with error code if any failed
    if failed:
        raise click.exceptions.Exit(1)
