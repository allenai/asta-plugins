"""Render customization fixtures with the same extension as the real example."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "plugins/asta-tools/skills/workspace/assets/_extensions/asta-slides"


def render(site):
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary)
        shutil.copytree(EXTENSION, project / "_extensions/asta-slides")
        (project / "custom.scss").write_text(
            "/*-- scss:defaults --*/\n$asta-link: #ffa31c;\n"
        )
        (project / "extra.html").write_text(
            "<script>window.astaCustomScript = true;</script>"
        )
        (project / "plugin.js").write_text(
            'window.ExamplePlugin = {id: "example-plugin", init: () => { window.astaCustomPlugin = true; }};'
        )
        for name, metadata, body in [
            ("no-sections", "", "## A slide without sections\n\nText.\n"),
            (
                "disabled",
                "format:\n  asta-slides-revealjs:\n    theme: default\nasta-slides:\n  section-header: false\n  controls: false\n  slide-number: false\n  dim-previous: false\n",
                "# Section\n\n## Content\n\nText.\n",
            ),
            (
                "rich-content",
                "author: Example speaker\ndate: 2026-01-01\n",
                "# Section\n\n## Code, table and callout\n\n"
                "```python\nanswer = 42\nprint(answer)\n```\n\n"
                "| Item | Value |\n|---|---|\n| Answer | 42 |\n\n"
                "::: {.callout-note}\nReadable note on a dark slide.\n:::\n\n"
                "> Readable quotation.\n",
            ),
            (
                "current",
                "asta-slides:\n  section-header: current\n",
                "# First section\n\n## One\n\nText.\n\n# Second section\n\n## Two\n\nText.\n",
            ),
            (
                "controls",
                "format:\n  asta-slides-revealjs:\n    controls: true\n",
                "# Section\n\n## One\n\nText.\n\n## Two\n\nText.\n",
            ),
            (
                "no-dividers",
                "asta-slides:\n  section-slides: false\n",
                "## Opening\n\nOwn title slide.\n\n# First section\n\n## One\n\nText.\n\n# Second section\n\n## Two\n\nText.\n",
            ),
            (
                "header-off",
                "asta-slides:\n  section-header: false\n",
                "# Section\n\n## Content\n\nText.\n",
            ),
            (
                "transition",
                "format:\n  asta-slides-revealjs:\n    transition: slide\n",
                "# Section\n\n## Content\n\nText.\n",
            ),
            (
                "scalar-options",
                "asta-slides: false\n",
                "# Section\n\n## Content\n\nText.\n",
            ),
            (
                "custom",
                "format:\n  asta-slides-revealjs:\n    theme: [default, _extensions/asta-slides/asta-slides.scss, custom.scss]\n    include-after-body: extra.html\n    revealjs-plugins:\n      - name: ExamplePlugin\n        path: .\n        script:\n          - path: plugin.js\n",
                "# Custom section\n\n## Custom slide\n\nText.\n",
            ),
        ]:
            path = project / f"{name}.qmd"
            default = (
                ""
                if name in {"custom", "disabled", "controls", "transition"}
                else "format: asta-slides-revealjs\n"
            )
            path.write_text(f"---\ntitle: {name}\n{default}{metadata}---\n\n{body}")
            subprocess.run(["quarto", "render", path.name], cwd=project, check=True)
            target = site / f"{name}.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path.with_suffix(".html"), target)


if __name__ == "__main__":
    render(Path(sys.argv[1]).resolve())
