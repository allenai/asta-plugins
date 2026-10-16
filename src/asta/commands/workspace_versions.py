"""Compare the installed asta release with a workspace's pinned rules ref."""

import re

from asta import __version__

# First release that publishes managed workspace rules.
OLDEST_RULES_REF = (0, 105, 0)
# Rules state the oldest CLI they work with; rules without this line predate it.
MIN_CLI_LINE = re.compile(rb"^ASTA_WORKSPACE_MIN_CLI\s*:?=\s*v?(\S+)\s*$", re.MULTILINE)
RELEASE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

Version = tuple[int, int, int]


def release(text: str) -> Version | None:
    """Parse a final release such as ``0.113.0`` or ``v0.113.0``; else None."""
    match = RELEASE.fullmatch(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def format_release(version: Version) -> str:
    return ".".join(str(part) for part in version)


def installed() -> Version | None:
    return release(__version__)


def install_command(version: Version) -> str:
    return (
        "uv tool install --force "
        f"git+https://github.com/allenai/asta-plugins.git@v{format_release(version)}"
    )


def rules_min_cli(rules: bytes) -> Version | None:
    match = MIN_CLI_LINE.search(rules)
    return release(match.group(1).decode()) if match else None


def cli_too_old(rules: bytes, ref: str, cli: Version | None) -> str | None:
    """Error text when the selected rules need a newer CLI than ``cli``."""
    needed = rules_min_cli(rules)
    if needed is None or cli is None or cli >= needed:
        return None
    return (
        f"asta-plugins@{ref} in .github/workflows/docs.yml needs asta "
        f"{format_release(needed)} or newer; this is asta {format_release(cli)}. "
        f"Update with: {install_command(needed)}"
    )


def pin_too_old(ref: str) -> str | None:
    """Error text when the pin predates the rules this CLI can load."""
    pinned = release(ref)
    if pinned is None or pinned >= OLDEST_RULES_REF:
        return None
    return (
        f"asta-plugins@{ref} predates managed workspace rules; this asta supports "
        f"v{format_release(OLDEST_RULES_REF)} or newer. Move the pin in "
        f".github/workflows/docs.yml to @v{format_release(OLDEST_RULES_REF)} or newer"
    )


def pin_behind(ref: str, cli: Version | None) -> str | None:
    """Notice when a final-release CLI is newer than a release pin; changes nothing."""
    pinned = release(ref)
    if pinned is None or cli is None or cli <= pinned:
        return None
    return (
        f"asta {format_release(cli)} is newer than the asta-plugins@{ref} pinned in "
        f".github/workflows/docs.yml. To move the pin, change @{ref} to "
        f"@v{format_release(cli)} there and run 'asta workspace sync'"
    )
