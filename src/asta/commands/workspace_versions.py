"""Compare the installed asta release with a workspace's pinned rules ref."""

import re

from asta import __version__

# First release that publishes managed workspace rules.
OLDEST_RULES_REF = (0, 105, 0)
# Rules state the oldest CLI they work with; rules without this line predate it.
MIN_CLI_LINE = re.compile(rb"^[ \t]*ASTA_WORKSPACE_MIN_CLI\b([^\n]*)$", re.MULTILINE)
MIN_CLI_VALUE = re.compile(r"\s*(?::{1,3}|\?)?=\s*(\S+)\s*")
RELEASE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
# PEP 440 subset the CLI's own version uses: pre, post, dev and local segments.
CLI_VERSION = re.compile(
    r"v?(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?(?:\.post(\d+))?(?:\.dev(\d+))?"
    r"(?:\+[a-z0-9.]+)?",
    re.IGNORECASE,
)
PRE_RANK = {"a": 0, "b": 1, "rc": 2}

Version = tuple[int, int, int]


def release(text: str) -> Version | None:
    """Parse a final release such as ``0.113.0`` or ``v0.113.0``; else None."""
    match = RELEASE.fullmatch(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def format_release(version: Version) -> str:
    return ".".join(str(part) for part in version)


def installed() -> str:
    return __version__


def cli_order(text: str) -> tuple | None:
    """PEP 440 sort key, so ``0.106.0.dev0`` sorts below ``0.106.0``; else None."""
    match = CLI_VERSION.fullmatch(text.strip())
    if match is None:
        return None
    major, minor, patch, pre, pre_n, post, dev = match.groups()
    if pre:
        stage = (PRE_RANK[pre.lower()], int(pre_n))
    elif dev is not None and post is None:
        stage = (-1, 0)
    else:
        stage = (3, 0)
    return (
        (int(major), int(minor), int(patch)),
        stage,
        -1 if post is None else int(post),
        float("inf") if dev is None else int(dev),
    )


def install_command(version: Version) -> str:
    return (
        "uv tool install --force "
        f"git+https://github.com/allenai/asta-plugins.git@v{format_release(version)}"
    )


def rules_min_cli(rules: bytes) -> Version | None:
    """The declared minimum CLI; raises ValueError if the declaration is unreadable."""
    match = MIN_CLI_LINE.search(rules)
    if match is None:
        return None
    line = match.group(1).decode(errors="replace")
    value = MIN_CLI_VALUE.fullmatch(line.split("#", 1)[0])
    needed = release(value.group(1)) if value else None
    if needed is None:
        raise ValueError(f"unreadable ASTA_WORKSPACE_MIN_CLI{line.rstrip()}")
    return needed


def cli_too_old(rules: bytes, ref: str, cli: str | None) -> str | None:
    """Error text when the selected rules need a newer CLI than ``cli``."""
    try:
        needed = rules_min_cli(rules)
    except ValueError as error:
        return (
            f"asta-plugins@{ref} in .github/workflows/docs.yml has an {error}; "
            "expected a release such as 'ASTA_WORKSPACE_MIN_CLI := 0.106.0'"
        )
    current = cli_order(cli) if cli else None
    if (
        needed is None
        or current is None
        or current >= cli_order(format_release(needed))
    ):
        return None
    return (
        f"asta-plugins@{ref} in .github/workflows/docs.yml needs asta "
        f"{format_release(needed)} or newer; this is asta {cli.strip()}. "
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


def pin_behind(ref: str, cli: str | None) -> str | None:
    """Notice when a final-release CLI is newer than a release pin; changes nothing."""
    pinned = release(ref)
    cli = release(cli) if cli else None
    if pinned is None or cli is None or cli <= pinned:
        return None
    return (
        f"asta {format_release(cli)} is newer than the asta-plugins@{ref} pinned in "
        f".github/workflows/docs.yml. To move the pin, change @{ref} to "
        f"@v{format_release(cli)} there and run 'asta workspace sync'"
    )
