"""The asta-pages widgets that link to files on disk: asta-files, asta-doc, asta-tests and
asta-theories tests=. A workflow page sits in pages/, renders into _site/pages/, and links each
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

    # Tests: one folder each, in the shapes runs write.
    tests = flow / "04-tests"
    _json(
        tests / "Q1-T1/result_summary.json",
        {
            "ran": True,
            "meets_threshold": True,
            "effect": 0.25,
            "effect_name": "mean difference",
            "p": 0.01,
            "n_animals": 6,
            "direction": "positive",
            "audit": {"big": list(range(10))},
        },
    )
    _write(tests / "Q1-T1/design.md", "# Committed test Q1-T1\n\nBody.\n")
    _write(tests / "Q1-T1/test.py", "print(1)\n")
    _write(tests / "Q1-T1/result.md", "# Result\n")
    _write(tests / "Q1-T1/fig_main.png", "png")
    # Larger than a page shows (2 MB): linked, not copied into the site.
    _write(tests / "Q1-T2/fig_all_panels.png", "x" * (2 * 1024 * 1024 + 1))
    _json(
        tests / "Q1-T2/result_summary.json",
        {
            "ran": True,
            "meets_threshold": {"RegionA": True, "RegionB": False, "rule": "both"},
            "effect": {"RegionA": 0.1, "RegionB": -0.2},
            "p": {"RegionA": 0.02, "RegionB": 0.4},
            "n_animals": {"RegionA": 5, "RegionB": 4},
        },
    )
    _json(tests / "Q1-T3/result_summary.json", {"ran": False, "status": "no data"})
    _write(tests / "Q1-T4/design.md", "# Committed test Q1-T4\n")  # still running
    # A reproduction's shape: several subject-level tests, a hypothesis in its design.
    _json(
        tests / "node_2_1/result_summary.json",
        {
            "runnable": True,
            "subject_level_tests": [
                {"name": "first", "n_mice": 5, "effect": None, "p": None},
                {"name": "second", "n_mice": 6, "effect": 1.5, "p": 0.03},
            ],
        },
    )
    _write(
        tests / "node_2_1/design.md",
        "# Committed test: node_2_1\n\n## Hypothesis (verbatim)\nSomething changes after a switch.\n\n"
        "```python\n# not a heading\n```\n",
    )
    _write(tests / "node_2_1/code.py", "pass\n")
    _write(tests / "seed.json", "{}")  # a flat file beside the test folders
    _json(
        flow / "04-tests/index.json",
        [
            {"test_id": "Q1-T1", "theory_name": "Theory one", "kind": "supporting"},
            {"test_id": "Q1-T2", "theory_name": "Theory  one\n"},
            {"test_id": "Q1-T9", "theory_name": "Theory two"},  # no folder yet
        ],
    )
    # A theory index whose tests live under <folder of the index>/tests/.
    _json(
        flow / "05-theories/G1/tests.json",
        [{"test_id": "G1-T1", "theory_name": "Theory two"}],
    )
    _json(
        flow / "05-theories/G1/tests/G1-T1/result_summary.json",
        {"meets_threshold": False},
    )
    _json(
        project / "pages/data/theorizer.json",
        {
            "theories": [
                {"id": "theory-1", "name": "Theory one", "query": "Q"},
                {"id": "theory-2", "name": "Theory two", "query": "Q"},
            ]
        },
    )
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


def _tests_data(page: str) -> dict:
    body = re.search(
        r'<script type="application/json" class="asta-tests-data"[^>]*>(.*?)</script>',
        page,
        re.S,
    ).group(1)
    return json.loads(body.replace("<\\/", "</"))


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    project = _project(tmp_path_factory.mktemp("widgets"))
    pages, log = _render(
        project,
        {
            "files": f'{{{{< asta-files dir="{FLOW}/01-survey" depth="2" >}}}}\n\n'
            f'{{{{< asta-files dir="{FLOW}/02-many" >}}}}',
            "doc": f'{{{{< asta-doc file="{FLOW}/03-map/map.md" >}}}}',
            "tests": f'{{{{< asta-tests dir="{FLOW}/04-tests" index="{FLOW}/04-tests/index.json" >}}}}',
            "theories": '{{< asta-theories data="data/theorizer.json" '
            f'tests="{FLOW}/04-tests/index.json,{FLOW}/05-theories/G1/tests.json" '
            f'tests_dir="{FLOW}/04-tests,{FLOW}/05-theories/G1/tests" >}}}}',
            "refused": '{{< asta-files dir="/etc" >}}\n\n{{< asta-doc file="../outside.md" >}}\n\n'
            '{{< asta-tests dir=".asta/../../x" >}}',
        },
    )
    return project, pages, log


def test_links_resolve_from_the_rendered_page_and_nothing_is_copied(site):
    project, pages, _ = site
    for name in ("files", "doc", "tests", "theories"):
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
    assert copies == [
        f"_{FLOW[1:]}/03-map/fig.png",
        f"_{FLOW[1:]}/04-tests/Q1-T1/fig_main.png",
    ]


def test_no_warnings_for_good_pages_and_refusals_for_paths_outside(site):
    _, pages, log = site
    warnings = [
        line for line in log.splitlines() if "WARN" in line or line.startswith("(W)")
    ]
    # The refused page's three shortcodes are the only warnings.
    assert len(warnings) == 3, warnings
    assert "/etc is an absolute path" in pages["refused"]
    assert "../outside.md leaves the project" in pages["refused"]
    assert "leaves the project" in pages["refused"].split("outside.md")[-1]


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


def test_tests_embed_each_folder_with_its_summary_and_links(site):
    _, pages, _ = site
    data = _tests_data(pages["tests"])
    tests = {t["id"]: t for t in data["tests"]}
    # Index order first, then folders the index does not name, in natural order.
    assert [t["id"] for t in data["tests"]] == [
        "Q1-T1",
        "Q1-T2",
        "Q1-T9",
        "node_2_1",
        "Q1-T3",
        "Q1-T4",
    ]
    one = tests["Q1-T1"]
    assert one["summary"]["meets_threshold"] is True
    assert "audit" not in one["summary"]
    assert one["index"]["theory_name"] == "Theory one"
    assert one["design"].endswith("Q1-T1/design.md")
    assert one["code"].endswith("Q1-T1/test.py")
    assert one["figures"] == [
        {
            "name": "fig_main.png",
            "href": f"../../{FLOW}/04-tests/Q1-T1/fig_main.png",
            "src": f"../_asta/files/_{FLOW[1:]}/04-tests/Q1-T1/fig_main.png",
        }
    ]
    big = tests["Q1-T2"]["figures"][0]
    assert big["name"] == "fig_all_panels.png" and "src" not in big
    assert big["size"] == "2.0 MB"
    assert tests["Q1-T9"] == {
        "id": "Q1-T9",
        "missing": True,
        "index": {"test_id": "Q1-T9", "theory_name": "Theory two"},
    }
    assert "summary" not in tests["Q1-T4"]
    assert tests["Q1-T3"]["summary"]["ran"] is False
    repro = tests["node_2_1"]
    assert repro["hypothesis"] == "Something changes after a switch."
    assert repro["heading"] == "Committed test: node_2_1"
    assert repro["codeName"] == "code.py"
    assert repro["summary"]["subject_level_tests"][1]["p"] == 0.03
    assert [o["name"] for o in data["others"]] == ["index.json", "seed.json"]


def test_theories_get_their_tests_from_each_index(site):
    _, pages, _ = site
    body = re.search(
        r'<script type="application/json" class="asta-theories-tests">(.*?)</script>',
        pages["theories"],
        re.S,
    ).group(1)
    tests = json.loads(body.replace("<\\/", "</"))["tests"]
    by_id = {t["id"]: t for t in tests}
    assert by_id["G1-T1"]["summary"] == {"meets_threshold": False}
    assert by_id["G1-T1"]["index"]["theory_name"] == "Theory two"
    assert by_id["Q1-T9"]["missing"] is True
    assert "tests.js" in pages["theories"]
    assert pages["theories"].index("tests.js") < pages["theories"].index("theories.js")
