"""Remote OCR command for PDF text extraction."""

import base64
from pathlib import Path

import click
import httpx

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
    "--start-page",
    type=int,
    default=0,
    show_default=True,
    help="First page to process (0-indexed)",
)
@click.option(
    "--max-pages",
    type=int,
    default=50,
    show_default=True,
    help="Maximum number of pages to process",
)
@click.option(
    "--images/--no-images",
    default=False,
    help="Extract and save images alongside the markdown output",
)
def remote(pdf: str, output: str | None, start_page: int, max_pages: int, images: bool):
    """Extract text from PDF using the Asta remote OCR API.

    Reads the PDF from disk, base64-encodes it, and sends it to the
    remote OCR endpoint via the Asta gateway.

    Examples:

        # Print extracted markdown to stdout
        asta pdf-extraction remote paper.pdf

        # Save to a file
        asta pdf-extraction remote paper.pdf -o paper.md

        # Process pages 50-99 of a large PDF
        asta pdf-extraction remote paper.pdf --start-page 50 -o paper-part2.md

        # Extract text and save embedded images next to the markdown
        asta pdf-extraction remote paper.pdf -o paper.md --images
    """
    api_config = get_api_config("remote-ocr")
    base_url = api_config["base_url"]
    auth_token = get_access_token()

    # Read and base64-encode the PDF
    with open(pdf, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode()

    click.echo(f"Processing {pdf}...", err=True)

    request_body: dict = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{pdf_b64}",
        },
        "pages": list(range(start_page, start_page + max_pages)),
    }
    if images:
        request_body["include_image_base64"] = True

    response = httpx.post(
        f"{base_url}/",
        headers={"Authorization": f"Bearer {auth_token}"},
        json=request_body,
        timeout=120.0,
    )

    if not response.is_success:
        raise click.ClickException(
            f"Remote OCR API error {response.status_code}: {response.text}"
        )

    data = response.json()
    markdown_parts = [
        page["markdown"] for page in data.get("pages", []) if page.get("markdown")
    ]
    markdown_str = "\n\n".join(markdown_parts)

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown_str)
        click.echo(f"Markdown saved to: {output_path}", err=True)
    else:
        click.echo(markdown_str)

    if images:
        image_dir = Path(output).parent if output else Path(".")
        image_count = 0
        for page in data.get("pages", []):
            for img in page.get("images", []):
                img_b64 = img.get("image_base64")
                if img_b64:
                    # Strip data URI prefix if present (e.g. "data:image/jpeg;base64,...")
                    if "," in img_b64:
                        img_b64 = img_b64.split(",", 1)[1]
                    (image_dir / img["id"]).write_bytes(
                        base64.standard_b64decode(img_b64)
                    )
                    image_count += 1
        click.echo(f"Saved {image_count} image(s) to {image_dir}", err=True)
