"""Generic passthrough command utility for external tools"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

import click


def ensure_tool_installed(
    tool_name: str,
    install_source: str,
    version: str,
    friendly_name: Optional[str] = None,
) -> Optional[Path]:
    """Check if a tool is installed, install if not.

    Args:
        tool_name: Name of the executable to check for (e.g., "asta-documents", "panda")
        install_source: Git URL to install from (e.g., "git+ssh://git@github.com/user/repo.git")
        version: Version tag to install (e.g., "v0.1.0", "main")
        friendly_name: Human-readable name for messages (defaults to tool_name)

    Returns:
        Path to executable or None if installation failed
    """
    display_name = friendly_name or tool_name

    # Check if tool is on PATH
    tool_path = shutil.which(tool_name)

    if tool_path:
        return Path(tool_path)

    # Not found, try to install it
    click.echo(
        f"{display_name} not found. Installing {version} from {install_source}...",
        err=True,
    )

    try:
        # Install using uv tool install with pinned version
        install_url = f"{install_source}@{version}" if version else install_source
        subprocess.run(
            ["uv", "tool", "install", install_url],
            capture_output=True,
            text=True,
            check=True,
        )

        click.echo(f"✓ {display_name} installed successfully", err=True)

        # Check again after installation
        tool_path = shutil.which(tool_name)
        if tool_path:
            return Path(tool_path)

        # Sometimes the tool isn't immediately on PATH, check common locations
        common_paths = [
            Path.home() / ".local" / "bin" / tool_name,
            Path.home() / ".cargo" / "bin" / tool_name,
        ]

        for path in common_paths:
            if path.exists() and path.is_file():
                return path

        click.echo(
            f"Warning: {display_name} was installed but not found on PATH", err=True
        )
        click.echo("You may need to add ~/.local/bin to your PATH", err=True)
        return None

    except subprocess.CalledProcessError as e:
        click.echo(f"Failed to install {display_name}: {e}", err=True)
        if e.stderr:
            click.echo(e.stderr, err=True)
        return None
    except FileNotFoundError:
        click.echo("Error: 'uv' command not found. Please install uv first:", err=True)
        click.echo("  curl -LsSf https://astral.sh/uv/install.sh | sh", err=True)
        return None


def create_passthrough_command(
    tool_name: str,
    install_source: str,
    version: str,
    command_name: str,
    friendly_name: Optional[str] = None,
    docstring: Optional[str] = None,
):
    """Create a Click command that passes through to an external tool.

    Args:
        tool_name: Name of the executable (e.g., "asta-documents", "panda")
        install_source: Git URL to install from
        version: Version tag to install
        command_name: Name for the Click command (e.g., "documents", "experiment")
        friendly_name: Human-readable name for messages
        docstring: Help text for the command

    Returns:
        A Click command function
    """
    display_name = friendly_name or tool_name

    @click.command(
        name=command_name,
        context_settings=dict(
            ignore_unknown_options=True,
            allow_interspersed_args=False,
            help_option_names=[],  # Disable Click's --help to pass it through
        ),
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def passthrough_command(ctx, args):
        """Passthrough command (docstring will be replaced)"""
        # Ensure tool is installed
        tool_path = ensure_tool_installed(
            tool_name, install_source, version, friendly_name
        )

        if not tool_path:
            raise click.ClickException(f"Could not find or install {display_name}")

        # Pass through to tool with all arguments
        try:
            result = subprocess.run(
                [str(tool_path)] + list(args),
                capture_output=True,
                text=True,
                check=False,  # Don't raise on non-zero exit
            )

            # Output stdout and stderr, replacing tool_name with "asta command_name"
            if result.stdout:
                output = result.stdout.replace(tool_name, f"asta {command_name}")
                click.echo(output, nl=False)
            if result.stderr:
                output = result.stderr.replace(tool_name, f"asta {command_name}")
                click.echo(output, nl=False, err=True)

            ctx.exit(result.returncode)
        except click.exceptions.Exit:
            raise
        except Exception as e:
            raise click.ClickException(f"Error running {display_name}: {e}")

    # Set custom docstring if provided
    if docstring:
        passthrough_command.__doc__ = docstring

    return passthrough_command
