"""Keep `$1`-style placeholders out of every SKILL.md.

When a skill runs, Claude Code replaces `$1`, `$2` and so on in its SKILL.md with the arguments
the skill was called with. So an awk `'{print $1}'` or a price like "$5" in a SKILL.md doesn't
reach the agent as written. Only SKILL.md is rewritten; a skill's other files may use `$1`.
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
