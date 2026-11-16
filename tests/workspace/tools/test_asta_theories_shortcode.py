"""The asta-theories shortcode embeds every data file it names, one script element each."""

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

from tests.workspace.test_workspace_what_changed import ASSETS


def _render(tmp_path: Path, shortcode: str) -> str:
    assert shutil.which("quarto")
    project = tmp_path / "site"
    shutil.copytree(
        ASSETS / "_extensions/asta-pages", project / "_extensions/asta-pages"
    )
    (project / "data").mkdir()
    for name, theory in (("theorizer.json", "One"), ("theorizer-v2.json", "Two")):
        data = {
            "theories": [{"id": "theory-1", "name": theory, "query": "Q </script>"}]
        }
        (project / "data" / name).write_text(json.dumps(data))
    (project / "theories.qmd").write_text(f"---\ntitle: Theories\n---\n\n{shortcode}\n")
    subprocess.run(
        ["quarto", "render", "theories.qmd", "--to", "html"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    return (project / "theories.html").read_text()


def _scripts(page: str) -> list[tuple[str, dict]]:
    found = re.findall(
        r'<script type="application/json" class="asta-theories-data"[^>]*data-asta-source="([^"]*)">(.*?)</script>',
        page,
        re.S,
    )
    return [(src, json.loads(body.replace("<\\/", "</"))) for src, body in found]


def test_several_data_files_each_embedded_in_order(tmp_path):
    page = _render(
        tmp_path,
        '{{< asta-theories data="data/theorizer.json, data/theorizer-v2.json" names="Original|Revised" >}}',
    )
    scripts = _scripts(page)
    assert [src for src, _ in scripts] == [
        "data/theorizer.json",
        "data/theorizer-v2.json",
    ]
    assert [d["theories"][0]["name"] for _, d in scripts] == ["One", "Two"]
    assert page.count('id="asta-theories-data"') == 1
    names = re.search(r'data-asta-names="([^"]*)"', page).group(1)
    assert json.loads(html.unescape(names)) == ["Original", "Revised"]
    assert "ap-error" not in page


def test_a_missing_file_gets_an_error_box_and_the_others_still_show(tmp_path):
    page = _render(
        tmp_path, '{{< asta-theories data="data/theorizer.json,data/missing.json" >}}'
    )
    assert [src for src, _ in _scripts(page)] == ["data/theorizer.json"]
    assert "cannot read the data file data/missing.json" in page
    assert 'class="asta-panel asta-theories"' in page
    assert (
        "data-asta-papers" not in page
    )  # no papers page named: theories.js uses literature.html


def test_the_papers_page_is_handed_to_the_panel(tmp_path):
    page = _render(
        tmp_path,
        '{{< asta-theories data="data/theorizer.json" papers="papers.html" >}}',
    )
    assert re.search(
        r'class="asta-panel asta-theories"[^>]*data-asta-papers="papers.html"', page
    )


def test_only_the_findings_a_theory_cites_are_embedded(tmp_path):
    _render(tmp_path, '{{< asta-theories data="data/theorizer.json" >}}')
    project = tmp_path / "site"
    data = {
        "papers": [{"key": "p1", "duplicates": []}],
        "theories": [
            {
                "id": "theory-1",
                "name": "One",
                "evidence_results": ["r1"],
                "statements": [],
            }
        ],
        "findings": {
            "s1": {
                "query": "q",
                "columns": [],
                "rows": [
                    {"result": "r1", "uuid": "u1", "paper": "p1", "data": {}},
                    {"result": "r2", "uuid": "u2", "paper": "p1", "data": {}},
                ],
            },
            "s2": {
                "query": "q",
                "columns": [],
                "rows": [{"result": "r3", "uuid": "u3", "paper": None, "data": {}}],
            },
        },
    }
    (project / "data" / "theorizer.json").write_text(json.dumps(data))
    subprocess.run(
        ["quarto", "render", "theories.qmd", "--to", "html"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    [(_, embedded)] = _scripts((project / "theories.html").read_text())
    assert embedded["findings"] == {
        "s1": {
            "query": "q",
            "columns": [],
            "rows": [{"result": "r1", "uuid": "u1", "paper": "p1", "data": {}}],
        }
    }
    assert embedded["papers"] == [
        {"key": "p1", "duplicates": []}
    ]  # empty lists stay lists
