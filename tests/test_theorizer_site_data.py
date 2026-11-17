"""theorizer-site-data takes a paper's authors, venue and DOI from the store entry's own record.

asta-papers writes the bibliographic record of the source a paper's text came from onto each
store entry (`authors`, `venue`, `doi`), and the project keeps the entry whole.
Semantic Scholar's record (`s2_metadata`) is the fallback for an entry without one.
"""

import importlib.machinery
import importlib.util
import json
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "plugins/asta-tools/skills/generate-theories/scripts/theorizer-site-data"
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


def _task(name: str, parts: list[dict]) -> dict:
    """A remote task's final JSON, its theory store sent as merge patches."""
    return {
        "id": name,
        "artifacts": [
            {
                "metadata": {
                    "type": "theory_store",
                    "merge_format": "json-merge-patch-rfc7396",
                },
                "parts": [{"kind": "data", "data": p} for p in parts],
            }
        ],
    }


def test_a_remote_runs_task_results_are_read_as_a_store(tmp_path):
    project = tmp_path / "theory"
    project.mkdir()
    schema = [{"name": "effect", "type": "str", "description": "The effect found"}]
    find = _task(
        "find-and-extract",
        [
            {
                "extraction_schemas": {
                    "extraction-schema-1": {
                        "id": "extraction-schema-1",
                        "schema": schema,
                        "extraction_query": "Find effects",
                    }
                }
            },
            {
                "paperstore": {
                    "p1": {"corpus_id": 7, "title": "A paper", "status": "full-text"}
                }
            },
            {
                "extraction_results": {
                    "r1": {
                        "paper_id": "p1",
                        "extraction_schema_id": "extraction-schema-1",
                        "extracted_data": [{"uuid": "u1", "effect": "up"}],
                    }
                }
            },
        ],
    )
    form = _task(
        "form-theory",
        [
            {
                "theories": {
                    "theory-1": {
                        "id": "theory-1",
                        "name": "A theory",
                        "theory_query": "Why?",
                        "components": {
                            "theory_name": "A theory",
                            "theory_statements": [],
                        },
                    }
                }
            }
        ],
    )
    (project / "find-and-extract.result.json").write_text(json.dumps(find))
    (project / "form-theory.result.json").write_text(json.dumps(form))
    data = _module().build(project)
    assert [p["key"] for p in data["papers"]] == ["p1"]
    table = data["findings"]["extraction-schema-1"]
    assert table["query"] == "Find effects"
    assert [c["name"] for c in table["columns"]] == ["effect"]
    assert len(table["rows"]) == 1
    assert len(data["theories"]) == 1


def test_only_versions_of_one_work_are_merged(tmp_path):
    project = tmp_path / "theory"
    project.mkdir()
    store = {
        "paperstore": {
            "pre": {
                "corpus_id": 1,
                "title": "Polio in Nigeria",
                "authors": ["Ada Obi"],
                "status": "full-text",
            },
            "pub": {
                "corpus_id": 2,
                "title": "Polio in Nigeria.",
                "authors": ["A. Obi"],
                "status": "full-text",
            },
            "other": {
                "corpus_id": 3,
                "title": "Polio in Nigeria",
                "authors": ["Kim Lee"],
                "status": "full-text",
            },
        }
    }
    (project / "paperstore.json").write_text(json.dumps(store))
    papers = _module().build(project)["papers"]
    assert len(papers) == 2
    merged = next(p for p in papers if p["duplicates"])
    assert {merged["key"], merged["duplicates"][0]["key"]} == {"pre", "pub"}


def test_searches_keep_their_query_count_zero_hits_and_list_every_paper(tmp_path):
    project = _project(tmp_path)
    searches = tmp_path / "searches"
    searches.mkdir()
    hit = {"externalIds": {"CorpusId": 1}, "title": "With its own record"}
    (searches / "s1.json").write_text(json.dumps({"total": 1, "data": [hit], "query": "first query"}))
    (searches / "s2.json").write_text(json.dumps({"total": 0, "offset": 0, "query": "nothing"}))
    (searches / "s3.json").write_text(json.dumps({"total": 1, "data": [hit], "query": "third query"}))
    data = _module().build(project)
    assert [(s["name"], s["query"], s["candidates"]) for s in data["searches"]] == [
        ("s1", "first query", 1), ("s2", "nothing", 0), ("s3", "third query", 1)]
    own = next(p for p in data["papers"] if p["key"] == "own")
    assert (own["search"], own["searches"]) == ("s1", ["s1", "s3"])


def test_evidence_citing_two_papers_names_both(tmp_path):
    project = _project(tmp_path)
    store = {
        "extraction_results": {
            "r1": {"paper_id": "own", "extraction_schema_id": "schema-1", "extracted_data": [{"uuid": "e1.1", "name_short": "a"}]},
            "r2": {"paper_id": "s2only", "extraction_schema_id": "schema-1", "extracted_data": [{"uuid": "e2.1", "name_short": "b"}]},
        },
        "theories": {"theory-1": {"id": "theory-1", "supporting_evidence_ids": ["r1", "r2"], "components": {
            "theory_name": "T", "theory_statements": [{"law": {"statement_name": "L", "supporting_evidence": [
                {"text": "both", "uuids": ["e1.1", "e2.1"]}]}}]}}},
    }
    (project / "theorystore.json").write_text(json.dumps(store))
    (t,) = _module().build(project)["theories"]
    ev = t["statements"][0]["evidence"][0]
    assert (ev["paper"], ev["papers"]) == ("own", ["own", "s2only"])
    assert (t["supporting_papers"], t["papers"]) == (2, ["own", "s2only"])


def test_a_gaps_file_keeps_the_theories_that_name_it(tmp_path):
    project = _project(tmp_path)
    theories = {f"theory-{i}": {"id": f"theory-{i}", "theory_query": q, "components": {"theory_name": n}}
                for i, (n, q) in enumerate([("G1: Gating", "q"), ("Drift", "G1: q"), ("G10: Other", "q"), ("None", "q")])}
    (project / "theorystore.json").write_text(json.dumps({"theories": theories}))
    out = tmp_path / "data" / "theorizer-G1.json"
    assert _module().main([str(project), str(out), "--gap", "G1"]) == 0
    data = json.loads(out.read_text())
    assert [(t["name"], t["gap"]) for t in data["theories"]] == [("G1: Gating", "G1"), ("Drift", "G1")]
    assert _module().main([str(project), str(out), "--gap", "G2"]) == 4


def test_set_aside_theories_are_left_out(tmp_path):
    project = _project(tmp_path)
    theories = {f"theory-{i}": {"id": f"theory-{i}", "components": {"theory_name": f"G1: T{i}"}} for i in (1, 2, 3)}
    (project / "theorystore.json").write_text(json.dumps({"theories": theories}))
    out = tmp_path / "data" / "theorizer-G1.json"
    assert _module().main([str(project), str(out), "--gap", "G1", "--exclude", "theory-2,theory-3"]) == 0
    assert [t["id"] for t in json.loads(out.read_text())["theories"]] == ["theory-1"]
