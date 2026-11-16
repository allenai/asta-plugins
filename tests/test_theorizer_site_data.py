"""theorizer-site-data takes a paper's authors, venue and DOI from the store entry's own record.

asta-papers writes the bibliographic record of the source a paper's text came from onto each
store entry (`authors`, `venue`, `doi`), and `theorize papers import` keeps the entry whole.
Semantic Scholar's record (`s2_metadata`) is the fallback for an entry without one.
"""

import importlib.machinery
import importlib.util
import json
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "plugins/asta-flows/skills/run-workflow/workflows/theory-generation/scripts/theorizer-site-data"
)


def _module():
    loader = importlib.machinery.SourceFileLoader("theorizer_site_data", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


S2 = {
    "authors": [{"name": "Zi-Ming Liu"}, {"name": "M. Tegmark"}],
    "venue": "arXiv.org",
    "externalIds": {"DOI": "10.0000/s2-doi"},
}


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "theory"
    project.mkdir()
    store = {
        "paperstore": {
            "own": {
                "corpus_id": 1,
                "title": "With its own record",
                "authors": ["Ziming Liu", "Max Tegmark"],
                "venue": "Advances in Neural Information Processing Systems",
                "doi": "10.48550/arXiv.2205.10343",
                "s2_metadata": S2,
            },
            "s2only": {
                "corpus_id": 2,
                "title": "Semantic Scholar only",
                "s2_metadata": S2,
            },
        }
    }
    (project / "paperstore.json").write_text(json.dumps(store))
    return project


def test_store_record_wins_and_semantic_scholar_fills_in(tmp_path):
    papers = {p["key"]: p for p in _module().build(_project(tmp_path))["papers"]}
    own, s2only = papers["own"], papers["s2only"]
    assert own["authors"] == ["Ziming Liu", "Max Tegmark"]
    assert own["venue"] == "Advances in Neural Information Processing Systems"
    assert own["doi"] == "10.48550/arXiv.2205.10343"
    assert s2only["authors"] == ["Zi-Ming Liu", "M. Tegmark"]
    assert s2only["venue"] == "arXiv.org"
    assert s2only["doi"] == "10.0000/s2-doi"


def test_bib_uses_the_store_record(tmp_path):
    module = _module()
    bib = tmp_path / "references.bib"
    module.add_bib(bib, module.build(_project(tmp_path))["papers"])
    text = bib.read_text()
    assert "Ziming Liu and Max Tegmark" in text
    assert "10.48550/arXiv.2205.10343" in text
    assert "Zi-Ming Liu and M. Tegmark" in text  # the entry without its own record


def _theories_project(tmp_path: Path) -> Path:
    project = tmp_path / "theory"
    project.mkdir()
    (project / "01-plan-theory-query.json").write_text(
        json.dumps({"theory_request": "The plan's wording"})
    )
    theories = {
        "theory-1": {
            "id": "theory-1",
            "name": "One",
            "theory_query": "Build theories about X.",
            "components": {},
        },
        "theory-2": {"id": "theory-2", "name": "Two", "components": {}},
    }
    (project / "theorystore.json").write_text(json.dumps({"theories": theories}))
    return project


def test_each_theory_carries_its_query(tmp_path):
    theories = {
        t["id"]: t for t in _module().build(_theories_project(tmp_path))["theories"]
    }
    assert theories["theory-1"]["query"] == "Build theories about X."
    assert theories["theory-2"]["query"] == "The plan's wording"  # no query of its own


def test_a_second_projects_papers_file_does_not_overwrite_the_first(tmp_path):
    module = _module()
    data = tmp_path / "data"
    assert module.papers_path(data / "theorizer.json") == data / "papers.json"
    assert module.papers_path(data / "theorizer-v2.json") == data / "papers-v2.json"
    assert module.papers_path(data / "other.json") == data / "other.papers.json"
    project = _theories_project(tmp_path)
    assert module.main([str(project), str(data / "theorizer-v2.json")]) == 0
    assert (data / "papers-v2.json").is_file()
    assert not (data / "papers.json").exists()


def test_a_collections_metadata_replaces_the_stores_for_its_documents(tmp_path):
    project = tmp_path / "theory"
    project.mkdir()
    hist = {
        "corpus_id": None,
        "title": "Research / Recherche",
        "publication_year": "1995",
        "status": "full-text",
        "s2_metadata": {
            "authors": [{"name": "A Comparison of Liquid Vaccine"}],
            "venue": None,
        },
    }
    store = {
        "paperstore": {
            "hist:a": hist,
            "hist:b": dict(hist, title="Other"),
            "hist:c": dict(hist, title="Kept"),
        }
    }
    (project / "paperstore.json").write_text(json.dumps(store))
    records = [
        {
            "id": "hist:a",
            "title": "Risk of vaccine-associated paralytic poliomyelitis",
            "year": None,
            "authors": [{"family": "Beale", "given": "A. J."}, {"literal": "WHO"}],
            "container": "The Lancet",
            "doi": "10.1/x",
        },
        {
            "id": "hist:b",
            "title": "Research / Recherche",
            "authors": [],
            "container": None,
        },
        {"id": "hist:missing", "title": "Not in the store"},
    ]
    papers = {p["key"]: p for p in _module().build(project, records)["papers"]}
    a = papers["hist:a"]
    assert (a["title"], a["authors"], a["venue"], a["doi"], a["year"]) == (
        "Risk of vaccine-associated paralytic poliomyelitis",
        ["A. J. Beale", "WHO"],
        "The Lancet",
        "10.1/x",
        "1995",
    )
    # hist:b now has hist:a's old title, so it is no longer merged with hist:a; an empty field keeps the store's.
    assert papers["hist:b"]["title"] == "Research / Recherche"
    assert papers["hist:b"]["authors"] == ["A Comparison of Liquid Vaccine"]
    assert papers["hist:c"]["title"] == "Kept"
