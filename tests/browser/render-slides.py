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
                "asta-slides:\n  theme: false\n  section-header: false\n  controls: false\n  slide-number: false\n  dim-previous: false\n",
                "# Section\n\n## Content\n\nText.\n",
            ),
            (
                "custom",
                "format:\n  asta-slides-revealjs:\n    theme: [default, _extensions/asta-slides/asta-slides.scss, custom.scss]\n    include-after-body: extra.html\n    revealjs-plugins:\n      - name: ExamplePlugin\n        path: .\n        script:\n          - path: plugin.js\n",
                "# Custom section\n\n## Custom slide\n\nText.\n",
            ),
        ]:
            path = project / f"{name}.qmd"
            default = "" if name == "custom" else "format: asta-slides-revealjs\n"
            path.write_text(f"---\ntitle: {name}\n{default}{metadata}---\n\n{body}")
            subprocess.run(["quarto", "render", path.name], cwd=project, check=True)
            target = site / "slide-fixtures" / f"{name}.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path.with_suffix(".html"), target)


if __name__ == "__main__":
    render(Path(sys.argv[1]).resolve())
