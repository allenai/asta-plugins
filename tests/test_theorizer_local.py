"""generate-theories/scripts/theorizer_local.py against the Theorizer library (asta-theorizer >= 0.1.5)."""

import importlib.util
import json
from pathlib import Path

import pytest

th = pytest.importorskip("theorizer")

SCRIPT = Path(__file__).resolve().parent.parent / "plugins/asta-tools/skills/generate-theories/scripts/theorizer_local.py"
spec = importlib.util.spec_from_file_location("theorizer_local", SCRIPT)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)

SCHEMA = [{"name": "effect", "type": "str", "description": "The effect"}]
RECORD = {"name_short": "A", "name_full": "Alpha", "brief_description": "Alpha raised gain.", "effect": "up"}


def law(uuid):
    return {"law": {"statement_name": "L", "theory_statement": "Alpha raises gain.", "supporting_evidence": [{"text": "e", "uuids": [uuid]}]}}


@pytest.fixture
def project(tmp_path, monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    local.open_project(str(tmp_path / "p"))
    return tmp_path / "p"


def test_written_records_and_theories_round_trip(project):
    records = local.write_records("paper-1", [dict(RECORD)], SCHEMA, "q")
    uuid = records[0]["uuid"]
    assert local.write_records("paper-1", [dict(RECORD)], SCHEMA, "q") == records  # once per paper
    ids = local.write_theories([{"theory_name": "T", "theory_description": "d", "theory_statements": [law(uuid)]}], "q")
    local.open_project(str(project))
    store = th.Project.get_theory_store()
    assert list(store.theories) == ids
    assert store.theories[ids[0]].supporting_evidence_ids == list(store.extraction_results)
    assert list(store.extraction_schemas) == ["schema-1"]


def test_unknown_citation_is_refused(project):
    local.write_records("paper-1", [dict(RECORD)], SCHEMA, "q")
    with pytest.raises(ValueError, match="e9.9"):
        local.write_theories([{"theory_name": "T", "theory_description": "d", "theory_statements": [law("e9.9")]}], "q")
    assert not th.Project.get_theory_store().theories


def test_papers_from_store_keeps_full_text_only(project, tmp_path):
    path = tmp_path / "store.json"
    path.write_text(json.dumps({"paperstore": {
        "s2-1": {"title": "Full", "publication_year": 2020, "paper_markdown": "# Full\ntext"},
        "s2-2": {"title": "Abstract only", "paper_markdown": "  "},
    }}))
    assert local.papers_from_store(str(path)) == [{"paper_id": "s2-1", "title": "Full", "year": 2020, "markdown": "# Full\ntext"}]
    assert list(json.loads((project / "paperstore.json").read_text())["paperstore"]) == ["s2-1"]


def test_generate_passes_each_stage_its_input(project, monkeypatch):
    the_plan = {"paper_search_query": "q", "extraction_query": "eq", "extraction_schema": SCHEMA, "theory_request_normalized": "tq"}
    calls = {}

    def plan_theory_query(question, mission_statement=None):
        calls["plan"] = (question, mission_statement)
        return {"output": the_plan}

    def extract_from_papers(papers, query, schema, extraction_schema_id):
        calls["extract"] = (query, schema, extraction_schema_id)
        result = th.Project.get_theory_store().add_extraction_result(th.Legacy.ExtractionQueryResult(
            paper_id="paper-1", extraction_schema_id=extraction_schema_id, extracted_data=[dict(RECORD)], potentially_relevant_new_papers=[]))
        return {"results": [{"paper_id": "paper-1", "extraction_result_id": result}], "failures": []}

    def generate_theories(records, query, mission_statement=None):
        calls["generate"] = (query, mission_statement)
        return {"theory_response": {"theories_general": [{"theory_name": "T", "theory_description": "d", "theory_statements": [law(records[0]["uuid"])]}]}}

    monkeypatch.setattr(th.Pipeline, "plan_theory_query", plan_theory_query)
    monkeypatch.setattr(th.Pipeline, "extract_from_papers", extract_from_papers)
    monkeypatch.setattr(th.Pipeline, "flatten_records", lambda packed: th.Project.get_theory_store().extraction_results[packed["results"][0]["extraction_result_id"]].extracted_data)
    monkeypatch.setattr(th.Pipeline, "generate_theories", generate_theories)

    p = local.plan("question", mission="m")
    out = local.extract([{"paper_id": "paper-1", "markdown": "x"}], p)
    ids = local.generate(out["records"], p, mission="m")
    assert calls == {"plan": ("question", "m"), "extract": ("eq", SCHEMA, "schema-1"), "generate": ("tq", "m")}
    assert th.Project.get_theory_store().theories[ids[0]].supporting_evidence_ids
