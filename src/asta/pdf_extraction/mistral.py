"""Mistral OCR command for PDF text extraction."""

import base64
from pathlib import Path

import click

from mistralai.client import Mistral

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config


@click.command()
@click.argument("pdf", type=click.Path(exists=True, readable=True))
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    default=None,
    help="Output file path for markdown (default: stdout)",
)
@click.option(
    "--max-pages",
    type=int,
    default=50,
    show_default=True,
    help="Maximum number of pages to process",
)
def mistral(pdf: str, output: str | None, max_pages: int):
    """Extract text from PDF using the Mistral OCR API.

    Reads the PDF from disk, base64-encodes it, and sends it to Mistral's
    OCR endpoint via the Asta gateway.

    Examples:

        # Print extracted markdown to stdout
        asta pdf-extraction mistral paper.pdf

        # Save to a file
        asta pdf-extraction mistral paper.pdf -o paper.md

        # Limit to first 10 pages
        asta pdf-extraction mistral paper.pdf --max-pages 10
    """
    api_config = get_api_config("mistral")
    server_url = api_config["base_url"]
    auth_token = get_access_token()

    # Read and base64-encode the PDF
    with open(pdf, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode()

    click.echo(f"Processing {pdf} with Mistral OCR...", err=True)

    client = Mistral(api_key=auth_token, server_url=server_url)
    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{pdf_b64}",
        },
        pages=list(range(max_pages)),
    )

    # Extract markdown from each page
    response_dict = ocr_response.model_dump() if hasattr(ocr_response, "model_dump") else ocr_response.dict()
    markdown_parts = [
        page["markdown"]
        for page in response_dict.get("pages", [])
        if page.get("markdown")
    ]
    markdown_str = "\n\n".join(markdown_parts)

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown_str)
        click.echo(f"Markdown saved to: {output_path}", err=True)
    else:
        click.echo(markdown_str)
