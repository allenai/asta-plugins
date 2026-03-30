"""PDF extraction commands."""

import click

from asta.pdf_extraction.passthrough import olmocr
from asta.pdf_extraction.remote import remote


@click.group(name="pdf-extraction")
def pdf_extraction():
    """Extract text from PDFs."""
    pass


pdf_extraction.add_command(olmocr)
pdf_extraction.add_command(remote)

__all__ = ["pdf_extraction"]
