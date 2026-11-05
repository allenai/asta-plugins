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
        (project / "backgrounds.scss").write_text(
            "/*-- scss:rules --*/\n"
            ".class-background { background-color: #173e44; "
            "background-image: linear-gradient(90deg, #173e44, #105257); }\n"
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
                "backgrounds",
                "",
                '## Shorthand background {background="#105257"}\n\nCustom slide color.\n\n'
                "### Nested heading\n\nNested heading content.\n\n"
                '## Explicit background {background-color="#0a3235"}\n\nCustom slide color.\n\n'
                "## Theme background\n\nDefault slide color.\n",
            ),
            (
                "background-classes",
                "format:\n  asta-slides-revealjs:\n    theme: [default, _extensions/asta-slides/asta-slides.scss, backgrounds.scss]\n",
                "## CSS background {.class-background}\n\nDeck CSS supplies the color and gradient.\n",
            ),
            (
                "vertical-backgrounds",
                "",
                '```{=html}\n<!-- vertical-stacks-start -->\n<section data-background="#233e58">\n'
                '<section id="inherited-one"><h2>Inherited background one</h2><p>Parent stack color.</p></section>\n'
                '<section id="inherited-two"><h2>Inherited background two</h2><p>The same parent color.</p></section>\n'
                "</section>\n<section>\n"
                '<section id="ordinary-one"><h2>Ordinary vertical slide</h2><p>The theme panel remains.</p></section>\n'
                '<section id="ordinary-two"><h2>Another ordinary slide</h2><p>The same theme panel.</p></section>\n'
                "</section>\n<!-- vertical-stacks-end -->\n```\n",
            ),
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
                if name
                in {
                    "custom",
                    "disabled",
                    "controls",
                    "transition",
                    "background-classes",
                }
                else "format: asta-slides-revealjs\n"
            )
            path.write_text(f"---\ntitle: {name}\n{default}{metadata}---\n\n{body}")
            subprocess.run(["quarto", "render", path.name], cwd=project, check=True)
            target = site / f"{name}.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == "vertical-backgrounds":
                # Pandoc wraps a raw-only body in an implicit slide. Unwrap it so
                # the fixture exercises native Reveal stacks at the top level.
                html = path.with_suffix(".html").read_text()
                start = html.index("<!-- vertical-stacks-start -->")
                end = html.index("<!-- vertical-stacks-end -->") + len(
                    "<!-- vertical-stacks-end -->"
                )
                wrapper = html.rfind("<section", 0, start)
                assert html[wrapper:start].strip() == '<section class="slide level2">'
                close = html.index("</section>", end) + len("</section>")
                target.write_text(html[:wrapper] + html[start:end] + html[close:])
            else:
                shutil.copyfile(path.with_suffix(".html"), target)


if __name__ == "__main__":
    render(Path(sys.argv[1]).resolve())
