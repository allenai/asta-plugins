"""Main CLI entry point for asta"""

import click

from asta import __version__
from asta.commands.auth import auth
from asta.documents import documents
from asta.experiment import experiment
from asta.literature.find import find
from asta.papers.author import author
from asta.papers.citations import citations
from asta.papers.get import get
from asta.papers.search import search
from asta.autodiscovery.commands import autodiscovery
from asta.pdf_extraction import pdf_extraction


@click.group()
@click.version_option(version=__version__, prog_name="asta")
def cli():
    """Asta - Tools for Scientific Workflows

    Use 'asta COMMAND --help' for more information on a specific command.
    """
    pass


@cli.group()
def literature():
    """Literature research commands"""
    pass


@cli.group()
def papers():
    """Semantic Scholar paper lookup and search"""
    pass


# Register auth commands
cli.add_command(auth)

# Register passthrough commands
cli.add_command(documents)
cli.add_command(experiment)
cli.add_command(pdf_extraction)
cli.add_command(autodiscovery)

# Register literature subcommands
literature.add_command(find)

# Register papers subcommands
papers.add_command(get)
papers.add_command(search)
papers.add_command(citations)
papers.add_command(author)


if __name__ == "__main__":
    cli()
