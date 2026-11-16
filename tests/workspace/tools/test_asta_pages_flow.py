"""Workflow pages, flat: pages/<NNNN>-<workflow>.qmd with only a title. The scaffold's sidebar
lists the front page, then the pages by file name (run order). Every page the asta-pages filter
runs on, the front page too, carries where the site's root is (script#asta-flow), so its feed
follows the sidebar, and each page's sections (script#asta-sections: its level-2 headings with
the ids Quarto gives them), which asta-pages.js lists under the page's sidebar link. All names
here are invented for the test."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.workspace.test_workspace_what_changed import ASSETS


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _page(path: Path, title: str) -> None:
    _write(
        path,
        f'---\ntitle: "{title}"\n---\n\n## Files\n\n{{{{< asta-files dir="notes" >}}}}\n',
    )


FRONT = """---
title: A long review title
---

The review.

## Mission

### A part of it

## Findings, état {#found}

## Notes {.unlisted}

```
## not a heading
```

## Next steps
"""


def _project(root: Path, extra: str = "") -> Path:
    """The scaffold's own project settings and sidebar contents, with the asta-pages filter."""
    project = root / "ws"
    shutil.copytree(
        ASSETS / "_extensions/asta-pages", project / "_extensions/asta-pages"
    )
    config = (ASSETS / "_quarto.yml").read_text()
    project_part = config[: config.index("\nbibliography:")]
    contents = re.search(r"    contents:\n(?:      .*\n)+", config).group(0)
    _write(
        project / "_quarto.yml",
        project_part
        + "\nfilters:\n  - asta-pages\n"
        + extra
        + "\nwebsite:\n  title: Demo\n  sidebar:\n"
        + contents
        + "format: html\n",
    )
    _write(project / "index.qmd", FRONT)
    return project


def _render(project: Path) -> tuple[dict[str, str], str]:
    done = subprocess.run(
        ["quarto", "render"], cwd=project, check=True, capture_output=True, text=True
    )
    html = {
        p.relative_to(project / "_site").as_posix(): p.read_text()
        for p in (project / "_site").rglob("*.html")
    }
    return html, done.stdout + done.stderr


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    assert shutil.which("quarto")
    project = _project(tmp_path_factory.mktemp("flow"))
    _write(project / "notes/a.md", "# A\n")
    _write(project / ".asta/flows/0001-alpha-study/workflow.mmd", "graph LR\n  a-->b\n")
    # Two runs of one workflow and one each of two others, written out of order.
    _page(project / "pages/0003-alpha-study.qmd", "Alpha study")
    _page(project / "pages/0004-gamma-review.qmd", "Gamma review")
    _page(project / "pages/0002-beta-check.qmd", "Beta check")
    # A page with the run's workflow diagram, which draws its own "Workflow" heading.
    _write(
        project / "pages/0001-alpha-study.qmd",
        '---\ntitle: "Alpha study"\n---\n\n'
        '{{< asta-workflow file="../.asta/flows/0001-alpha-study/workflow.mmd" >}}\n\n'
        '## Same\n\n## Same\n\n## Files\n\n{{< asta-files dir="notes" >}}\n',
    )
    return _render(project)


def _sidebar(page: str) -> list[tuple[str, str]]:
    """The sidebar's links in order: (text, href)."""
    nav = page[page.index('id="quarto-sidebar"') :]
    nav = nav[: nav.index("</nav>")]
    out = []
    for attrs, text in re.findall(
        r'<a ([^>]*sidebar-link[^>]*)>\s*(?:<span class="menu-text">)?([^<]*)', nav
    ):
        href = re.search(r'href="([^"]*)"', attrs)
        out.append((text.strip(), href.group(1) if href else ""))
    return out


def _data(page: str, name: str):
    found = re.findall(
        rf'<script type="application/json" id="asta-{name}">(.*?)</script>', page, re.S
    )
    assert len(found) <= 1, f"asta-{name} once per page"
    return json.loads(found[0].replace("<\\/", "</")) if found else None


def _level2_ids(page: str) -> list[str]:
    return re.findall(r'<section id="([^"]+)" class="level2', page)


def test_the_sidebar_lists_the_front_page_then_the_pages_flat_in_run_order(site):
    html, log = site
    assert "WARN" not in log
    page = html["pages/0002-beta-check.html"]
    assert _sidebar(page) == [
        ("Home", "../index.html"),
        ("Alpha study", "../pages/0001-alpha-study.html"),
        ("Beta check", "../pages/0002-beta-check.html"),
        ("Alpha study", "../pages/0003-alpha-study.html"),
        ("Gamma review", "../pages/0004-gamma-review.html"),
    ]
    assert "sidebar-item-section" not in page, "no sections"


def test_every_page_the_filter_runs_on_says_where_the_site_root_is(site):
    html, _ = site
    assert _data(html["index.html"], "flow") == {
        "format": "asta-pages/flow@3",
        "site": "./",
    }, "the front page starts the feed"
    for name in ("pages/0001-alpha-study.html", "pages/0004-gamma-review.html"):
        assert _data(html[name], "flow") == {
            "format": "asta-pages/flow@3",
            "site": "../",
        }


def test_each_page_lists_every_page_s_sections_with_the_ids_quarto_gives_them(site):
    html, _ = site
    data = _data(html["pages/0002-beta-check.html"], "sections")
    assert data["site"] == "../"
    pages = data["pages"]
    assert pages["index.html"] == [
        {"id": "mission", "title": "Mission"},
        {"id": "found", "title": "Findings, état"},
        {"id": "next-steps", "title": "Next steps"},
    ], "level 2 only, explicit ids kept, .unlisted and code left out"
    assert pages["pages/0001-alpha-study.html"] == [
        {"id": "workflow", "title": "Workflow"},
        {"id": "same", "title": "Same"},
        {"id": "same-1", "title": "Same"},
        {"id": "files", "title": "Files"},
    ]
    assert list(pages) == [
        "index.html",
        "pages/0001-alpha-study.html",
        "pages/0002-beta-check.html",
        "pages/0003-alpha-study.html",
        "pages/0004-gamma-review.html",
    ]
    # Every id names a section of the rendered page.
    for name, sections in pages.items():
        ids = _level2_ids(html[name])
        assert all(s["id"] in ids for s in sections), (name, ids)
    assert _data(html["index.html"], "sections") == {**data, "site": "./"}


def test_sidebar_sections_can_be_turned_off_for_the_site(tmp_path):
    project = _project(tmp_path, "\nasta-pages:\n  sidebar-sections: false\n")
    html, _ = _render(project)
    assert _data(html["index.html"], "sections") is None
    assert _data(html["index.html"], "flow") is not None, "the feed stays"
