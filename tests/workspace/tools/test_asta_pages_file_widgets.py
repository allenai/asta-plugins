"""The asta-pages widgets that link to files on disk: asta-files and asta-doc. A workflow page sits in pages/, renders into _site/pages/, and links each
file under .asta/flows/ relative to the rendered page, without Quarto copying the files."""

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

from tests.workspace.test_workspace_what_changed import ASSETS

FLOW = ".asta/flows/0001-demo-flow"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _json(path: Path, data) -> None:
    _write(path, json.dumps(data))


def _project(tmp_path: Path) -> Path:
    """A small website project with one flow's files, all invented for the test."""
    assert shutil.which("quarto")
    project = tmp_path / "ws"
    shutil.copytree(
        ASSETS / "_extensions/asta-pages", project / "_extensions/asta-pages"
    )
    _write(
        project / "_quarto.yml",
        'project:\n  type: website\n  output-dir: _site\n  render: [index.qmd, "pages/*.qmd"]\n'
        "website:\n  title: Demo\nformat: html\n",
    )
    _write(project / "index.qmd", "---\ntitle: Home\n---\n\nHome.\n")
    flow = project / FLOW

    # A step's folder: a subfolder, files, and names the listing leaves out.
    step = flow / "01-survey"
    _write(step / "notes.md", "# Notes\n\nSee [the table](tables/t1.csv).\n")
    _write(step / "tables/t1.csv", "a,b\n1,2\n")
    _write(step / "__pycache__/x.pyc", "")
    _write(step / ".DS_Store", "")
    _write(step / "api_key.txt", "not shown")
    _write(step / ".env", "not shown")
    many = flow / "02-many"
    for i in range(40):
        _write(many / f"part-{i:02d}.txt", "x" * i)

    # A step's own document, with a link and an image beside it.
    _write(
        flow / "03-map/map.md",
        "# Map of open questions\n\nIntro with an @handle and [the data](data/rows.csv).\n\n"
        "## First question\n\n![A figure](fig.png)\n\n### Detail\n\nText.\n",
    )
    _write(flow / "03-map/data/rows.csv", "x\n")
    _write(flow / "03-map/fig.png", "png")

    return project


def _render(project: Path, pages: dict[str, str]) -> tuple[dict[str, str], str]:
    for name, body in pages.items():
        _write(
            project / "pages" / f"{name}.qmd", f"---\ntitle: {name}\n---\n\n{body}\n"
        )
    done = subprocess.run(
        ["quarto", "render"], cwd=project, check=True, capture_output=True, text=True
    )
    out = {
        name: (project / "_site/pages" / f"{name}.html").read_text() for name in pages
    }
    return out, done.stdout + done.stderr


def _links(page: str) -> list[str]:
    """Every href and src into .asta/: attributes, and links in the panels' JSON."""
    found = [
        html.unescape(h)
        for h in re.findall(r'\b(?:href|src)="([^"]*\.asta/[^"]*)"', page)
    ]

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and x.startswith("../") and ".asta/" in x:
            found.append(x)

    for body in re.findall(
        r'<script type="application/json"[^>]*>(.*?)</script>', page, re.S
    ):
        walk(json.loads(body.replace("<\\/", "</")))
    return found


def _resolves(project: Path, link: str) -> bool:
    target = project / "_site/pages" / unquote(link)
    target = Path(os.path.normpath(target))
    return target.is_dir() if link.endswith("/") else target.is_file()


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    project = _project(tmp_path_factory.mktemp("widgets"))
    pages, log = _render(
        project,
        {
            "files": f'{{{{< asta-files dir="{FLOW}/01-survey" depth="2" >}}}}\n\n'
            f'{{{{< asta-files dir="{FLOW}/02-many" >}}}}',
            "doc": f'{{{{< asta-doc file="{FLOW}/03-map/map.md" >}}}}',
            "refused": '{{< asta-files dir="/etc" >}}\n\n{{< asta-doc file="../outside.md" >}}',
        },
    )
    return project, pages, log


def test_links_resolve_from_the_rendered_page_and_nothing_is_copied(site):
    project, pages, _ = site
    for name in ("files", "doc"):
        links = _links(pages[name])
        assert links, name
        assert all(link.startswith(f"../../{FLOW}/") for link in links), name
        broken = [link for link in links if not _resolves(project, link)]
        assert broken == [], name
    assert not any(".asta" in str(p) for p in (project / "_site").rglob("*"))
    # The figures the pages show are copied into the site, and only those.
    copies = sorted(
        p.relative_to(project / "_site/_asta/files").as_posix()
        for p in (project / "_site/_asta/files").rglob("*")
        if p.is_file()
    )
    assert copies == [f"_{FLOW[1:]}/03-map/fig.png"]


def test_no_warnings_for_good_pages_and_refusals_for_paths_outside(site):
    _, pages, log = site
    warnings = [
        line for line in log.splitlines() if "WARN" in line or line.startswith("(W)")
    ]
    # The refused page's two shortcodes are the only warnings.
    assert len(warnings) == 2, warnings
    assert "/etc is an absolute path" in pages["refused"]
    assert "../outside.md leaves the project" in pages["refused"]


def test_files_lists_folders_first_with_sizes_and_skips_caches_and_secrets(site):
    _, pages, _ = site
    page = pages["files"]
    first = page.split('class="asta-panel asta-files"')[1]
    names = re.findall(r'<a href="[^"]*" title="[^"]*">([^<]*)</a>', first)
    assert names[:4] == ["01-survey/", "tables/", "t1.csv", "notes.md"]
    for hidden in ("__pycache__", ".DS_Store", "api_key.txt", ".env"):
        assert hidden not in first
    assert "8 B" in first  # t1.csv
    many = page.split('class="asta-panel asta-files"')[2]
    assert many.count(">part-") == 30
    assert "10 more" in many and "open the folder" in many


def test_doc_renders_inline_with_headings_moved_under_the_page(site):
    _, pages, _ = site
    page = pages["doc"]
    assert re.search(r"<h3[^>]*>\s*Map of open questions", page)
    assert re.search(r"<h4[^>]*>\s*First question", page)
    assert re.search(r"<h5[^>]*>\s*Detail", page)
    assert f'href="../../{FLOW}/03-map/data/rows.csv"' in page
    # A figure is shown from its copy in the site; its link still opens the workspace's file.
    assert f'src="../_asta/files/_{FLOW[1:]}/03-map/fig.png"' in page
    assert ">map.md</a>" in page  # the header line links the file
    assert "@handle" in page  # not read as a citation
