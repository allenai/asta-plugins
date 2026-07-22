"""Main CLI entry point for asta"""

import click
from asta_artifact.cli import main as artifacts

from asta import __version__
from asta.analyze_data import analyze_data
from asta.autodiscovery.commands import autodiscovery
from asta.commands.auth import auth
from asta.documents import documents
from asta.experiment import experiment
from asta.literature.find import find
from asta.literature.interactive import interactive
from asta.papers.author import author
from asta.papers.citations import citations
from asta.papers.get import get
from asta.papers.search import search
from asta.papers.snippet_search import snippet_search
from asta.patents.forward_citations import forward_citations
from asta.patents.get import get as patent_get
from asta.patents.search import search as patent_search
from asta.pdf_extraction import pdf_extraction
from asta.theorizer import generate_theories


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


@cli.group()
def patents():
    """Patent (USPTO) lookup, BM25 search, and forward citations"""
    pass


# Register auth commands
cli.add_command(auth)

# Register generate-theories commands
cli.add_command(generate_theories)

# Register analyze-data commands
cli.add_command(analyze_data)

# Register artifacts command
cli.add_command(artifacts, name="artifacts")

# Register passthrough commands
cli.add_command(documents)
cli.add_command(experiment)
cli.add_command(pdf_extraction)
cli.add_command(autodiscovery)

# Register literature subcommands
literature.add_command(find)
literature.add_command(interactive)

# Register papers subcommands
papers.add_command(get)
papers.add_command(search)
papers.add_command(snippet_search)
papers.add_command(citations)
papers.add_command(author)

# Register patent subcommands
patents.add_command(patent_get, name="get")
patents.add_command(patent_search, name="search")
patents.add_command(forward_citations)


if __name__ == "__main__":
    cli()
