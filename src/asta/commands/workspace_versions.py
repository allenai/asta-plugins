"""Compare the installed asta release with a workspace's pinned rules ref."""

import re

from packaging.version import InvalidVersion, Version

from asta import __version__

# First release that publishes managed workspace rules.
OLDEST_RULES_REF = (0, 105, 0)
# Rules state the oldest CLI they work with; rules without this line predate it.
MIN_CLI_LINE = re.compile(
    rb"^[ \t]*(?:(?:override|export)[ \t]+)*ASTA_WORKSPACE_MIN_CLI\b([^\n]*)$",
    re.MULTILINE,
)
MIN_CLI_VALUE = re.compile(r"\s*(?::{1,3}|\?)?=\s*(\S+)\s*")
RELEASE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

Release = tuple[int, int, int]


def release(text: str) -> Release | None:
    """Parse a final release such as ``0.113.0`` or ``v0.113.0``; else None."""
    match = RELEASE.fullmatch(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def format_release(version: Release) -> str:
    return ".".join(str(part) for part in version)


def installed() -> str:
    return __version__


def cli_version(text: str) -> Version | None:
    """PEP 440 version, so ``0.106.0.dev0`` sorts below ``0.106.0``; else None."""
    try:
        return Version(text.strip())
    except InvalidVersion:
        return None


def install_ref(ref: str, needed: Release) -> str:
    """The pinned ref when its CLI satisfies ``needed``, else the minimum release."""
    pinned = release(ref)
    if pinned is None:
        return ref
    return f"v{format_release(max(pinned, needed))}"


def install_command(ref: str) -> str:
    return (
        f"uv tool install --force git+https://github.com/allenai/asta-plugins.git@{ref}"
    )


def _pin(ref: str, source: str | None) -> str:
    return f"asta-plugins@{ref} in {source}" if source else f"asta-plugins@{ref}"


def rules_min_cli(rules: bytes) -> Release | None:
    """The last declared minimum CLI, as Make reads it; ValueError if unreadable."""
    matches = list(MIN_CLI_LINE.finditer(rules))
    if not matches:
        return None
    line = matches[-1].group(1).decode(errors="replace")
    value = MIN_CLI_VALUE.fullmatch(line.split("#", 1)[0])
    needed = release(value.group(1)) if value else None
    if needed is None:
        raise ValueError(f"unreadable ASTA_WORKSPACE_MIN_CLI{line.rstrip()}")
    return needed


def cli_too_old(
    rules: bytes, ref: str, cli: str | None, source: str | None = None
) -> str | None:
    """Error text when the selected rules need a newer CLI than ``cli``."""
    try:
        needed = rules_min_cli(rules)
    except ValueError as error:
        return (
            f"{_pin(ref, source)} has an {error}; "
            "expected a release such as 'ASTA_WORKSPACE_MIN_CLI := 0.106.0'"
        )
    if needed is None:
        return None
    update = f"Update with: {install_command(install_ref(ref, needed))}"
    current = cli_version(cli) if cli else None
    if current is None:
        shown = f" {cli.strip()!r}" if cli else ""
        return (
            f"{_pin(ref, source)} needs asta {format_release(needed)} or newer; "
            f"cannot read this asta's version{shown}. {update}"
        )
    if current >= Version(format_release(needed)):
        return None
    return (
        f"{_pin(ref, source)} needs asta {format_release(needed)} or newer; "
        f"this is asta {cli.strip()}. {update}"
    )


def pin_too_old(ref: str, source: str | None = None) -> str | None:
    """Error text when the pin predates the rules this CLI can load."""
    pinned = release(ref)
    if pinned is None or pinned >= OLDEST_RULES_REF:
        return None
    where = f" in {source}" if source else ""
    return (
        f"asta-plugins@{ref} predates managed workspace rules; this asta supports "
        f"v{format_release(OLDEST_RULES_REF)} or newer. Move the asta-plugins pin"
        f"{where} to @v{format_release(OLDEST_RULES_REF)} or newer"
    )


def pin_behind(ref: str, cli: str | None, source: str | None = None) -> str | None:
    """Notice when a final-release CLI is newer than a release pin; changes nothing."""
    pinned = release(ref)
    current = release(cli) if cli else None
    if pinned is None or current is None or current <= pinned:
        return None
    where = f" in {source}" if source else ""
    return (
        f"asta {format_release(current)} is newer than the pinned {_pin(ref, source)}. "
        f"To move the pin, change @{ref} to @v{format_release(current)}{where} "
        "and run 'asta workspace sync'"
    )
