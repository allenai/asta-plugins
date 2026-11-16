"""asta-pages autolink: links in a page's text open a card of what they point at, and mentions
of tests, theories, gaps and experiments become such links. All names and data here are
invented for the test."""

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.workspace.test_workspace_what_changed import ASSETS

RUN = ".asta/flows/0001-explore/01-run"
REPRO = ".asta/flows/0002-repro"
GAPS = ".asta/flows/0003-gaps"
FIGS = ".asta/flows/0004-review/01-figures"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _json(path: Path, data) -> None:
    _write(path, json.dumps(data))


def _node(n: str, idx: int, parent: str) -> dict:
    return {
        "id": n,
        "parent_id": parent,
        "creation_idx": idx,
        "success": True,
        "hypothesis": f"Hypothesis of {n}.",
    }


BIB = """@article{ref-one,
  title = {{A study of alpha}},
  author = {Ada Lovelace and Alan Turing},
  year = {2020},
  journal = {Journal of Examples},
  doi = {10.1000/example.1},
  url = {https://www.semanticscholar.org/paper/abc123}
}
"""

REVIEW = """---
title: Review
bibliography: references.bib
evidence:
  E-1:
    quote: "alpha held in every case we looked at"
    cite: ref-one
---

## Results for node_2_1

The seed, Experiment 3, held. node_2_1 held as well, and node_2_1 again.
A run-only experiment node_2_2 and an unknown node_9_9; also node_2_10 is not node_2_1x.

Theory "Q1 – Alpha  rule   holds" passed T-1 (see `node_2_1` and [node_2_1](https://example.org)).
[Alpha held]{.ev key="E-1"} as reported [@ref-one]. Q1 again, and Q1.

See the [paper](https://doi.org/10.1000/example.1), the [data](https://data.example.org/d1),
a [site](https://www.example.com/page) and [the notes](notes/a.md).

Figure 1 shows it, as does @fig-one.

::: {#fig-one}
![](fig.png)

Alpha across mice, n = 5. More words here.
:::

::: {#fig-two}
![](fig2.png)

A figure with no record of what it was made from.
:::

::: {#fig-three}
![](fig3.png)

A figure whose record names a file that is not there.
:::

## Data

{{< asta-datasets >}}

| Dataset | Link |
|---|---|
| Not in datasets.json | [elsewhere](https://other.example.net/x) |

Q1 in a new section, and Q9 is no gap.
"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    assert shutil.which("quarto")
    project = tmp_path_factory.mktemp("autolink") / "ws"
    for ext in ("asta-pages", "evidence"):
        shutil.copytree(ASSETS / "_extensions" / ext, project / "_extensions" / ext)
    _write(
        project / "_quarto.yml",
        'project:\n  type: website\n  output-dir: _site\n  render: [index.qmd, "pages/*.qmd"]\n'
        "website:\n  title: Demo\nformat: html\n"
        "filters:\n  - _extensions/evidence/snippet.lua\n  - asta-pages\n",
    )
    _write(project / "index.qmd", REVIEW)
    _write(project / "references.bib", BIB)
    _write(project / "notes/a.md", "# Notes\n")
    _json(
        project / ".asta/datasets.json",
        [
            {
                "id": "d1",
                "name": "Example data one",
                "released_by": "Example Lab",
                "used_for": "Test T-1",
                "links": [{"label": "data", "url": "https://data.example.org/d1"}],
            }
        ],
    )
    _write(project / "fig.png", "png")
    _write(project / "fig2.png", "png")
    _write(project / "fig3.png", "png")
    # What the figures were made from: fig-one's folder is named for it; fig-three's record is
    # found by its id; fig-two has none.
    _json(project / FIGS / "fig-one/audit.json", {"verdict": "PASS"})
    _write(project / FIGS / "fig-one/make_figure.py", "print(1)\n")
    _json(
        project / FIGS / "fig-one/figure.json",
        {
            "id": "fig-one",
            "script": "make_figure.py",
            "inputs": ["notes/a.md", "notes/b.csv", "notes/c.csv", "notes/d.csv"],
            "audit": "audit.json",
        },
    )
    for name in ("b.csv", "c.csv", "d.csv"):
        _write(project / "notes" / name, "x\n")
    _json(
        project / FIGS / "third/figure.json",
        {
            "id": "fig-three",
            "inputs": [
                "notes/a.md",
                "notes/missing.csv",
                "/data/archive/session-1.nwb",
            ],
        },
    )
    # An AutoDS run seeded from a hosted experiment (mcts_node_1_0 loads the data).
    _json(
        project / RUN / "args.json",
        {"dataset_metadata": "/elsewhere/workspace/inputs/seed/metadata.json"},
    )
    _json(
        project / "inputs/seed/metadata.json",
        {
            "lineage": {
                "parent_run_id": "run-0",
                "seed_experiment": "Experiment ID 3 (node_2_4)",
            }
        },
    )
    _json(
        project / "inputs/seed/source-experiment-3.node_2_4.json",
        {"hypothesis": "The seed hypothesis.", "normalized_surprisal": 0.25},
    )
    for n, idx, parent in [
        ("node_1_0", 1, "node_0_0"),
        ("node_2_1", 2, "node_1_0"),
        ("node_2_2", 3, "node_1_0"),
        ("node_2_10", 4, "node_1_0"),
    ]:
        _json(project / RUN / f"mcts_{n}.json", _node(n, idx, parent))
    _write(
        project / "pages/0001-explore.qmd",
        f'---\ntitle: "Explore"\n---\n\n{{{{< asta-autods data="../{RUN}" >}}}}\n',
    )
    # Reproduction tests, and the seed's test, which the selection names in `seed`.
    for t in ("node_2_1", "node_2_10", "S00"):
        _json(
            project / REPRO / "tests" / t / "result_summary.json",
            {"verdict": "supported", "effect": 0.4, "p": 0.008, "n_mice": 7},
        )
    _json(
        project / REPRO / "selection.json",
        {
            "groups": {"node_2_1": [], "node_2_10": []},
            "seed": {"test_id": "S00", "experiment": 3},
        },
    )
    _write(
        project / "pages/0002-repro.qmd",
        f'---\ntitle: "Reproduce"\n---\n\n{{{{< asta-tests dir="{REPRO}/tests" index="{REPRO}/selection.json#groups" >}}}}\n',
    )
    # Two theories runs for one gap, a test of one theory, and a gap map.
    _json(
        project / GAPS / "data/theorizer-Q1a.json",
        {
            "theories": [
                {
                    "id": "theory-1",
                    "name": "Q1 — Alpha rule holds",
                    "query": "Q1 (weighted): does alpha hold?",
                    "gap": "Q1",
                    "summary": "Alpha holds across mice.",
                    "supporting": 4,
                    "conflicting": 1,
                    "statements": [],
                }
            ]
        },
    )
    _json(
        project / GAPS / "data/theorizer-Q1b.json",
        {
            "theories": [
                {
                    "id": "theory-1",
                    "name": "Q1 — Alpha is drift",
                    "query": "a second pass",
                    "gap": "Q1",
                    "statements": [],
                },
                {
                    "id": "theory-2",
                    "name": "Q9 has no gap field",
                    "query": "Q9: a query that only starts with an id",
                    "statements": [],
                },
            ]
        },
    )
    _json(
        project / GAPS / "cards/tests.json",
        [
            {
                "test_id": "T-1",
                "theory_name": "Q1 — Alpha rule holds",
                "kind": "supporting",
                "dataset": "D1",
            }
        ],
    )
    _json(
        project / GAPS / "tests/T-1/result_summary.json",
        {"meets_threshold": True, "effect": 0.3, "p": 0.01, "n_mice": 6},
    )
    _write(
        project / GAPS / "map/gaps.md",
        "## Gaps\n\n- [Q1, open] Does alpha hold? See T-1 and the [notes](../../../../notes/a.md).\n",
    )
    _write(
        project / "pages/0003-gaps.qmd",
        '---\ntitle: "Gaps"\n---\n\n## Gap map\n\n'
        f'{{{{< asta-doc file="{GAPS}/map/gaps.md" >}}}}\n\n## Theories\n\n'
        f'{{{{< asta-theories data="../{GAPS}/data/theorizer-Q1a.json,../{GAPS}/data/theorizer-Q1b.json" '
        f'tests="{GAPS}/cards/tests.json" tests_dir="{GAPS}/tests" >}}}}\n\n'
        f'{{{{< asta-tests dir="{GAPS}/tests" index="{GAPS}/cards/tests.json" >}}}}\n',
    )
    done = subprocess.run(
        ["quarto", "render"], cwd=project, check=True, capture_output=True, text=True
    )
    pages = {
        name: (project / "_site" / name).read_text()
        for name in ("index.html", "pages/0003-gaps.html")
    }
    return pages, done.stdout + done.stderr


def _main(page: str) -> str:
    return page[page.index("<main") : page.index("</main>")]


def _store(page: str) -> dict:
    body = re.search(
        r'<script type="application/json" class="asta-cards-data">(.*?)</script>',
        page,
        re.S,
    ).group(1)
    return json.loads(body.replace("<\\/", "</"))


def _links(main: str) -> list[tuple[str, str]]:
    return [
        (re.sub(r"<[^>]+>", "", html.unescape(text)), href)
        for href, text in re.findall(
            r'<a href="([^"]+)" class="asta-al[^"]*"[^>]*>(.*?)</a>', main, re.S
        )
    ]


def test_mentions_link_to_their_widgets(site):
    pages, log = site
    assert "WARN" not in log
    assert _links(_main(pages["index.html"])) == [
        ("Experiment 3", "pages/0002-repro.html#test-S00"),
        ("node_2_1", "pages/0002-repro.html#test-node_2_1"),
        ("node_2_2", "pages/0001-explore.html#node-2-2"),
        ("node_2_10", "pages/0002-repro.html#test-node_2_10"),
        ("Q1 – Alpha rule holds", "pages/0003-gaps.html#theory-1"),
        ("T-1", "pages/0003-gaps.html#test-T-1"),
        ("Q1", "pages/0003-gaps.html#query-1"),
        ("Figure 1", "#fig-one"),
        ("T-1", "pages/0003-gaps.html#test-T-1"),
        ("Q1", "pages/0003-gaps.html#query-1"),
    ]


def test_a_gap_links_once_a_section_and_lists_every_theories_run(site):
    pages, _ = site
    gap = _store(pages["index.html"])["m:Q1"]["sections"]
    assert [s.get("title") for s in gap[:2]] == ["does alpha hold?", "a second pass"]
    assert gap[0]["role"] == "Gap Q1"
    assert gap[0]["facts"] == ["1 theory"]
    assert [t["id"] for t in gap[0]["tally"]] == ["T-1"]
    assert gap[1]["href"] == "pages/0003-gaps.html#query-2"
    assert gap[2]["links"][0]["label"] == "Gap map entry"
    entry = gap[2]["links"][0]["href"].split("#")[1]
    assert f'id="{entry}"' in pages["pages/0003-gaps.html"]


def test_cards_of_a_node_a_seed_a_test_and_a_theory(site):
    pages, _ = site
    store = _store(pages["index.html"])
    node = store["m:node_2_1"]
    assert [(s["role"], s["href"]) for s in node["sections"]] == [
        ("Discovery", "pages/0001-explore.html#node-2-1"),
        ("Verification", "pages/0002-repro.html#test-node_2_1"),
    ]
    assert node["sections"][0]["title"] == "Experiment 1 · node_2_1"
    assert node["foot"] == "Clicking node_2_1 opens the test."
    seed = store["m:Experiment 3"]["sections"]
    assert seed[0]["href"] == "https://autodiscovery.allen.ai/runs/shared/run-0?exp=3"
    assert seed[0]["text"] == "The seed hypothesis."
    assert seed[1]["href"] == "pages/0002-repro.html#test-S00"
    test = store["m:T-1"]["sections"][0]
    assert test["facts"] == ["dataset D1"]
    assert test["text"] == "Tests Q1 — Alpha rule holds (supporting)"
    assert test["test"]["summary"]["meets_threshold"] is True
    theory = store["m:Q1 - Alpha rule holds"]["sections"][0]
    assert theory["text"] == "Alpha holds across mice."
    assert theory["clamp"] == 4
    assert theory["facts"] == ["4 supporting", "1 conflicting findings"]
    assert [t["id"] for t in theory["tests"]] == ["T-1"]


def test_cards_of_links_citations_evidence_figures_and_files(site):
    pages, _ = site
    page = pages["index.html"]
    store = _store(page)
    paper = store["x:https://doi.org/10.1000/example.1"]
    assert paper["sections"][0]["title"] == "A study of alpha"
    assert (
        paper["sections"][0]["sub"]
        == "Ada Lovelace, Alan Turing · 2020 · Journal of Examples"
    )
    assert paper["foot"] == "Opens in a new tab."
    data = store["x:https://data.example.org/d1"]["sections"][0]
    assert (data["role"], data["title"], data["sub"], data["text"]) == (
        "Dataset",
        "Example data one",
        "Released by Example Lab",
        "Used for: Test T-1",
    )
    site_card = store["x:https://www.example.com/page"]["sections"][0]
    assert site_card["role"] == "example.com"
    cite = [v for k, v in store.items() if k.startswith("c:ref-one")][0]["sections"]
    assert cite[0]["quote"] == "alpha held in every case we looked at"
    assert [link["label"] for link in cite[-1]["links"]] == ["Semantic Scholar", "DOI"]
    ev = [v for k, v in store.items() if k.startswith("e:")][0]["sections"]
    assert ev[0]["quote"] == "alpha held in every case we looked at"
    figure = store["g:fig-one"]["sections"][0]
    assert (figure["title"], figure["image"], figure["text"]) == (
        "Figure 1",
        "fig.png",
        "Alpha across mice, n = 5.",
    )
    assert figure["facts"] == ["n = 5", "audit: PASS"]
    assert store["f:notes/a.md"]["file"] is True
    # The file card's title links to the file, the same target as the mention.
    assert store["f:notes/a.md"]["sections"][0]["href"].endswith("notes/a.md")
    # Every external link opens in a new tab; no link with a card keeps a native title.
    for tag in re.findall(r"<a [^>]*data-asta-card[^>]*>", _main(page)):
        assert " title=" not in tag
        if 'href="http' in tag:
            assert 'target="_blank"' in tag


def test_datasets_come_from_datasets_json(site):
    pages, _ = site
    page = pages["index.html"]
    main = _main(page)
    # The widget's table, from .asta/datasets.json, with its link carded and its ids linked.
    table = re.search(r"<table.*?Example data one.*?</table>", main, re.S).group(0)
    assert "Example Lab" in table
    assert re.search(r'Test <a href="[^"]*#test-T-1"', table), "an id in Used for links"
    assert 'data-asta-card="x:https://data.example.org/d1"' in table
    store = _store(page)
    assert store["x:https://data.example.org/d1"]["sections"][0]["role"] == "Dataset"
    # A table headed "Dataset" no longer makes its links datasets: only datasets.json does.
    other = store["x:https://other.example.net/x"]["sections"][0]
    assert other["role"] == "other.example.net"


def test_a_gap_is_the_theories_gap_field(site):
    pages, _ = site
    store = _store(pages["index.html"])
    assert "m:Q9" not in store, "a query that starts with an id names no gap"
    assert "#query-" not in str([t for t, _ in _links(_main(pages["index.html"]))])


def test_a_figure_shows_what_it_was_made_from(site):
    pages, log = site
    page = pages["index.html"]
    lines = re.findall(r'<div class="asta-made-from">(.*?)</div>', page, re.S)
    assert len(lines) == 2, "fig-one and fig-three; fig-two has no figure.json"
    one, three = lines
    hrefs = re.findall(r'href="([^"]+)"', one)
    assert hrefs == [
        f"../{FIGS}/fig-one/make_figure.py",
        "../notes/a.md",
        "../notes/b.csv",
        "../notes/c.csv",
        "../notes/d.csv",
        f"../{FIGS}/fig-one/audit.json",
    ]
    assert re.sub(r"<[^>]+>", "", one).startswith("Made from make_figure.py · 4 inputs")
    assert ">audit PASS</a>" in one
    # A file the record names that is not there: a warning, and no link to it.
    assert "missing.csv" in three and 'missing.csv"' not in three
    assert "(missing)" in three
    assert "figure fig-three: input notes/missing.csv not found" in log
    # Data outside the workspace is named, never linked, and does not warn.
    assert (
        'session-1.nwb</span> <span class="asta-made-missing">(outside the workspace)'
        in three
    )
    assert "session-1.nwb" not in log
    card = _store(page)["g:fig-one"]["sections"][0]
    assert [link["label"] for link in card["links"]] == [
        "make_figure.py",
        "a.md",
        "b.csv",
        "c.csv",
        "+1 more",
        "audit PASS",
    ]
    assert card["links"][4]["href"] == f"../{FIGS}/fig-one/"


def test_workflow_pages_link_their_own_prose(site):
    pages, _ = site
    gaps = pages["pages/0003-gaps.html"]
    assert 'href="0003-gaps.html#test-T-1"' in _main(gaps)
    assert "f:notes/a.md" in _store(gaps)


def test_headings_code_links_and_one_mention_per_paragraph(site):
    pages, _ = site
    main = _main(pages["index.html"])
    heading = re.search(r"<h2[^>]*>.*?</h2>", main, re.S).group(0)
    assert "asta-al" not in heading
    assert "<code>node_2_1</code>" in main
    assert "node_9_9" in main and "#node-9-9" not in main
    first_para = re.search(r"<p>The seed.*?</p>", main, re.S).group(0)
    assert first_para.count('href="pages/0002-repro.html#test-node_2_1"') == 1
