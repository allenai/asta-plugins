"""Generic passthrough command utility for external tools"""

import re
import shutil
import subprocess
from pathlib import Path

import click


def get_installed_version(tool_path: Path) -> str | None:
    """Get the version of an installed tool by running --version.

    Args:
        tool_path: Path to the tool executable

    Returns:
        Version string (e.g., "v0.1.0" or "0.1.0") or None if version cannot be determined
    """
    try:
        result = subprocess.run(
            [str(tool_path), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

        if result.returncode != 0:
            return None

        # Parse version from output (handles various formats)
        output = result.stdout.strip()
        # Look for version patterns like "v1.2.3", "1.2.3", "tool v1.2.3", "tool 1.2.3"
        version_match = re.search(r"v?\d+\.\d+(?:\.\d+)?(?:[.-][\w.]+)?", output)
        if version_match:
            return version_match.group(0)

        return None

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return None


def parse_semver(version: str) -> tuple[int, int, int] | None:
    """Parse a semantic version string into (major, minor, patch) tuple.

    Args:
        version: Version string (e.g., "v1.2.3", "1.2.3", "0.1.0")

    Returns:
        Tuple of (major, minor, patch) or None if not a valid semantic version
    """
    if not version:
        return None

    # Remove 'v' prefix if present
    version_str = version.lstrip("v")

    # Match x.y.z format (ignore any additional parts like -beta, +build)
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version_str)
    if not match:
        return None

    try:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except (ValueError, AttributeError):
        return None


def validate_semver(version: str) -> bool:
    """Validate that a version string is in semantic version format.

    Args:
        version: Version string to validate

    Returns:
        True if valid x.y.z format, False otherwise
    """
    return parse_semver(version) is not None


def version_meets_minimum(installed: str | None, minimum: str) -> bool:
    """Check if installed version meets the minimum required version.

    Args:
        installed: Installed version string (or None if not found)
        minimum: Minimum required version (must be x.y.z format)

    Returns:
        True if installed version >= minimum, False otherwise

    Raises:
        ValueError: If minimum version is not in valid x.y.z format
    """
    if not installed:
        return True

    # Validate minimum version format
    min_tuple = parse_semver(minimum)
    if min_tuple is None:
        raise ValueError(
            f"Invalid minimum_version format: '{minimum}'. Must be x.y.z (e.g., '0.1.0', '1.2.3')"
        )

    # Parse installed version
    installed_tuple = parse_semver(installed)
    if installed_tuple is None:
        # If we can't parse the installed version, we can't verify it meets minimum
        # Conservative approach: assume it doesn't meet minimum
        return False

    # Compare tuples: (major, minor, patch)
    return installed_tuple >= min_tuple


def install_tool(
    tool_name: str,
    install_type: str,
    install_source: str,
    minimum_version: str,
    friendly_name: str | None = None,
    force: bool = False,
) -> bool:
    """Install or reinstall a tool using uv.

    Args:
        tool_name: Name of the executable
        install_type: Type of installation source ("pypi", "git", or "local")
        install_source: Source location (package name, git URL, or filesystem path)
        minimum_version: Minimum version tag to install
        friendly_name: Human-readable name for messages
        force: If True, use --force to reinstall

    Returns:
        True if installation succeeded, False otherwise

    Raises:
        ValueError: If install_type is not valid
    """
    display_name = friendly_name or tool_name

    # Validate install_type
    valid_types = ("pypi", "git", "local")
    if install_type not in valid_types:
        raise ValueError(
            f"Invalid install_type: '{install_type}'. Must be one of: {', '.join(valid_types)}"
        )

    action = "Reinstalling" if force else "Installing"
    click.echo(
        f"{action} {display_name} (>= {minimum_version}) from {install_type} source...",
        err=True,
    )

    try:
        # Construct install URL based on type
        if install_type == "pypi":
            # PyPI: package-name>=minimum_version or just package-name
            # uv will install the latest version that satisfies the constraint
            install_url = f"{install_source}>={minimum_version}"
        elif install_type == "git":
            # Git: git+https://...@v{version} or git+https://...@{version}
            # For git, we install the specific tag matching minimum_version
            install_url = f"{install_source}@v{minimum_version}"
        elif install_type == "local":
            # Local: /path/to/package or ~/path/to/package
            # Expand ~ to home directory
            expanded_path = Path(install_source).expanduser()
            install_url = str(expanded_path)
        else:
            # Should not reach here due to validation above
            raise ValueError(f"Unsupported install_type: {install_type}")

        cmd = ["uv", "tool", "install", install_url]
        if force:
            cmd.append("--force")

        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        click.echo(f"✓ {display_name} installed successfully", err=True)
        return True

    except subprocess.CalledProcessError as e:
        click.echo(f"Failed to install {display_name}: {e}", err=True)
        if e.stderr:
            click.echo(e.stderr, err=True)
        return False
    except FileNotFoundError:
        click.echo("Error: 'uv' command not found. Please install uv first:", err=True)
        click.echo("  curl -LsSf https://astral.sh/uv/install.sh | sh", err=True)
        return False


def ensure_tool_installed(
    tool_name: str,
    install_type: str,
    install_source: str,
    minimum_version: str,
    friendly_name: str | None = None,
) -> Path | None:
    """Check if a tool is installed with minimum required version, install/update if needed.

    Args:
        tool_name: Name of the executable to check for (e.g., "asta-documents", "panda")
        install_type: Type of installation source ("pypi", "git", or "local")
        install_source: Source location (package name, git URL, or filesystem path)
        minimum_version: Minimum required version (e.g., "0.1.0", "1.2.3")
        friendly_name: Human-readable name for messages (defaults to tool_name)

    Returns:
        Path to executable or None if installation failed

    Raises:
        ValueError: If minimum_version is not in valid x.y.z format or install_type is invalid
    """
    display_name = friendly_name or tool_name

    # Validate minimum_version format
    if not validate_semver(minimum_version):
        raise ValueError(
            f"Invalid minimum_version for {display_name}: '{minimum_version}'. "
            "Must be in x.y.z format (e.g., '0.1.0', '1.2.3')"
        )

    # Check if tool is on PATH
    tool_path = shutil.which(tool_name)

    if tool_path:
        tool_path_obj = Path(tool_path)

        # Check if installed version meets minimum
        installed_version = get_installed_version(tool_path_obj)

        try:
            if version_meets_minimum(installed_version, minimum_version):
                # Version is good, return the path
                return tool_path_obj

            # Version is too old - need to update
            click.echo(
                f"{display_name} version {installed_version or 'unknown'} is below minimum {minimum_version}",
                err=True,
            )

        except ValueError as e:
            # Should not happen since we validated above, but just in case
            raise click.ClickException(str(e))

        # Reinstall with minimum version
        if install_tool(
            tool_name,
            install_type,
            install_source,
            minimum_version,
            friendly_name,
            force=True,
        ):
            # Verify installation
            tool_path = shutil.which(tool_name)
            if tool_path:
                return Path(tool_path)

        return None

    # Not found, try to install it
    click.echo(f"{display_name} not found.", err=True)

    if install_tool(
        tool_name, install_type, install_source, minimum_version, friendly_name
    ):
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


def create_passthrough_command(
    tool_name: str,
    install_type: str,
    install_source: str,
    minimum_version: str,
    command_name: str,
    friendly_name: str | None = None,
    docstring: str | None = None,
):
    """Create a Click command that passes through to an external tool.

    Args:
        tool_name: Name of the executable (e.g., "asta-documents", "panda")
        install_type: Type of installation source ("pypi", "git", or "local")
        install_source: Source location (package name, git URL, or filesystem path)
        minimum_version: Minimum required version in x.y.z format
        command_name: Name for the Click command (e.g., "documents", "experiment")
        friendly_name: Human-readable name for messages
        docstring: Help text for the command

    Returns:
        A Click command function
    """
    display_name = friendly_name or tool_name

    @click.command(
        name=command_name,
        help=docstring,  # Set help text directly in decorator
        context_settings=dict(
            ignore_unknown_options=True,
            allow_interspersed_args=False,
            help_option_names=[],  # Disable Click's --help to pass it through
        ),
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def passthrough_command(ctx, args):
        """Passthrough command"""
        # Ensure tool is installed with minimum version
        tool_path = ensure_tool_installed(
            tool_name, install_type, install_source, minimum_version, friendly_name
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

    return passthrough_command
