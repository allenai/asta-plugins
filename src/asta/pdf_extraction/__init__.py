"""PDF extraction commands."""

import click

from asta.pdf_extraction.mistral import mistral
from asta.pdf_extraction.passthrough import olmocr


@click.group(name="pdf-extraction")
def pdf_extraction():
    """Extract text from PDFs using olmOCR or Mistral OCR."""
    pass


pdf_extraction.add_command(olmocr)
pdf_extraction.add_command(mistral)

__all__ = ["pdf_extraction"]
