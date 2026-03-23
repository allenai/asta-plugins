"""PDF processing commands using PyMuPDF (local extraction)"""

import click

from asta.pdf_extraction_local.batch_extract import batch_extract
from asta.pdf_extraction_local.to_text import to_text


@click.group(name="pdf-extraction-local")
def pdf_extraction_local():
    """PDF processing commands using PyMuPDF (local, no server required)"""
    pass


pdf_extraction_local.add_command(to_text)
pdf_extraction_local.add_command(batch_extract)

__all__ = ["pdf_extraction_local"]
