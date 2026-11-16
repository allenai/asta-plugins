"""SKILL.md text that the skill loader would change.

The loader replaces `$1`, `$2` and so on with the skill's arguments, so a price like "$1" or an
awk `$1` in a SKILL.md reaches the agent as one of the person's words. Other files in a skill
folder are read as they are.
"""

import re
from pathlib import Path

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def test_no_positional_placeholders_in_skill_md():
    hits = [
        f"{path.relative_to(PLUGINS)}:{n}: {line.strip()}"
        for path in PLUGINS.glob("*/skills/*/SKILL.md")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"\$\d", line)
    ]
    assert not hits, "\n".join(hits)
