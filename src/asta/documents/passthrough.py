"""Pass-through command for asta-documents CLI"""

import shutil
import subprocess
from pathlib import Path

import click


def ensure_asta_documents_installed():
    """Check if asta-documents is installed, install if not.

    Returns:
        Path to asta-documents executable or None if installation failed
    """
    # Check if asta-documents is on PATH
    asta_docs_path = shutil.which("asta-documents")

    if asta_docs_path:
        return Path(asta_docs_path)

    # Not found, try to install it
    click.echo(
        "asta-documents not found. Installing from git@github.com:allenai/asta-resource-repo.git...",
        err=True,
    )

    try:
        # Install using uv tool install
        subprocess.run(
            [
                "uv",
                "tool",
                "install",
                "git+ssh://git@github.com/allenai/asta-resource-repo.git",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        click.echo("✓ asta-documents installed successfully", err=True)

        # Check again after installation
        asta_docs_path = shutil.which("asta-documents")
        if asta_docs_path:
            return Path(asta_docs_path)

        # Sometimes the tool isn't immediately on PATH, check common locations
        common_paths = [
            Path.home() / ".local" / "bin" / "asta-documents",
            Path.home() / ".cargo" / "bin" / "asta-documents",
        ]

        for path in common_paths:
            if path.exists() and path.is_file():
                return path

        click.echo(
            "Warning: asta-documents was installed but not found on PATH", err=True
        )
        click.echo("You may need to add ~/.local/bin to your PATH", err=True)
        return None

    except subprocess.CalledProcessError as e:
        click.echo(f"Failed to install asta-documents: {e}", err=True)
        if e.stderr:
            click.echo(e.stderr, err=True)
        return None
    except FileNotFoundError:
        click.echo("Error: 'uv' command not found. Please install uv first:", err=True)
        click.echo("  curl -LsSf https://astral.sh/uv/install.sh | sh", err=True)
        return None


@click.command(
    context_settings=dict(
        ignore_unknown_options=True,
        allow_interspersed_args=False,
        help_option_names=[],  # Disable Click's --help to pass it through
    )
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def documents(ctx, args):
    """Document metadata index management (pass-through to asta-documents CLI).

    This command passes all arguments directly to the asta-documents CLI.
    If asta-documents is not installed, it will be installed automatically.

    Examples:
        asta documents list
        asta documents add <url> --name="Title" --summary="Description"
        asta documents search --summary="query"
        asta documents get <uuid>

    For full documentation, run: asta documents --help
    """
    # Ensure asta-documents is installed
    asta_docs_path = ensure_asta_documents_installed()

    if not asta_docs_path:
        raise click.ClickException("Could not find or install asta-documents")

    # Pass through to asta-documents with all arguments
    try:
        result = subprocess.run(
            [str(asta_docs_path)] + list(args),
            capture_output=True,
            text=True,
            check=False,  # Don't raise on non-zero exit, let asta-documents handle it
        )

        # Output stdout and stderr, replacing "asta-documents" with "asta documents"
        if result.stdout:
            output = result.stdout.replace("asta-documents", "asta documents")
            click.echo(output, nl=False)
        if result.stderr:
            output = result.stderr.replace("asta-documents", "asta documents")
            click.echo(output, nl=False, err=True)

        ctx.exit(result.returncode)
    except click.exceptions.Exit:
        # Re-raise Exit exceptions (from ctx.exit) - don't catch them
        raise
    except Exception as e:
        raise click.ClickException(f"Error running asta-documents: {e}")
