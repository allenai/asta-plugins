"""``make what-changed`` detects ``-n`` from MAKEFLAGS on GNU Make 3.81 and 4.x."""

import re
import subprocess
from pathlib import Path

import pytest

MK = (
    Path(__file__).parent.parent
    / "plugins/asta-tools/skills/workspace/assets/workspace.mk"
)


def _dry_run_check():
    line = next(
        ln for ln in MK.read_text().splitlines() if "what-changed: dry run" in ln
    )
    return re.sub(r"\s*\\$", "", line.strip()).replace("$$", "$")


@pytest.mark.parametrize(
    ("makeflags", "dry"),
    [
        ("n", True),
        ("-n", True),
        ("rn", True),
        ("n -- WHAT_CHANGED_BASE=main", True),
        # GNU Make 3.81 (macOS /usr/bin/make) puts command-line variables first.
        ("WHAT_CHANGED_BASE=main -n", True),
        ("WHAT_CHANGED_BASE=main", False),
        ("WHAT_CHANGED_BASE=main --", False),
        ("-- WHAT_CHANGED_BASE=main", False),
        ("w -- WHAT_CHANGED_BASE=main", False),
        ("--no-print-directory", False),
        ("-I/tmp/nope", False),
        ("", False),
    ],
)
def test_dry_run_detection(makeflags, dry):
    script = f"{_dry_run_check()} echo ran"
    out = subprocess.run(
        ["sh", "-c", script],
        env={"MAKEFLAGS": makeflags, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ("dry run" in out) is dry
    assert ("ran" in out.splitlines()[-1]) is not dry


def test_missing_deck_review_says_why_and_how_to_fix():
    """An older Asta CLI syncs no deck-review.py; make says so instead of silently diffing text."""
    text = MK.read_text()
    check = next(ln for ln in text.splitlines() if "deck-review.py' ]" in ln)
    assert "$(dir $(call workspace_script,what-changed.py))deck-review.py" in check
    message = next(ln for ln in text.splitlines() if "showing slides as text" in ln)
    assert (
        "upgrade the Asta CLI" in message and "asta workspace sync --refresh" in message
    )
