"""generate-theories/scripts/theorizer_local.py against the Theorizer library (asta-theorizer >= 0.2.0)."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

th = pytest.importorskip("theorizer")

SCRIPT = Path(__file__).resolve().parent.parent / "plugins/asta-tools/skills/generate-theories/scripts/theorizer_local.py"
spec = importlib.util.spec_from_file_location("theorizer_local", SCRIPT)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)

SCHEMA = [{"name": "effect", "type": "str", "description": "The effect"}]
RECORD = {"name_short": "A", "name_full": "Alpha", "brief_description": "Alpha raised gain.", "effect": "up"}


def law(uuids):
    return {"law": {"statement_name": "L", "theory_statement": "Alpha raises gain.", "supporting_evidence": [{"text": "e", "uuids": uuids}]}}


def theory(*statements):
    return {"theory_name": "T", "theory_description": "d", "theory_statements": list(statements)}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(th.Config, "USER_CONFIG_DIR", str(tmp_path / "keys"))
    for key in th.Config.KEY_ENV_VARS.values():
        monkeypatch.delenv(key, raising=False)
    local.open_without_keys(str(tmp_path / "p"))
    return tmp_path / "p"


def test_open_without_keys_loads_no_key(tmp_path, monkeypatch):
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / th.Config.API_KEY_FILENAME).write_text(json.dumps({"openai": "sk-from-file"}))
    monkeypatch.setattr(th.Config, "USER_CONFIG_DIR", str(keys))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-shell")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    local.open_without_keys(str(tmp_path / "p"))
    assert not os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY")


def test_written_records_and_theories_round_trip(project):
    records = local.write_records("paper-1", [dict(RECORD)], SCHEMA, "q")
    uuid = records[0]["uuid"]
    assert local.write_records("paper-1", [dict(RECORD)], SCHEMA, "q") == records  # once per paper
    assert [(r["uuid"], r["paper_id"], r["schema_id"]) for r in local.records()] == [(uuid, "paper-1", "schema-1")]
    ids = local.write_theories([theory(law([uuid]))], "q")
    local.open_without_keys(str(project))
    store = th.Project.get_theory_store()
    assert list(store.theories) == ids
    saved = store.theories[ids[0]]
    assert saved.supporting_evidence_ids == list(store.extraction_results)
    assert (saved.components["method"], saved.model_str) == ("written", "written")
    assert list(store.extraction_schemas) == ["schema-1"]


def test_a_record_missing_a_slot_is_refused(project):
    with pytest.raises(ValueError, match="effect"):
        local.write_records("paper-1", [{k: v for k, v in RECORD.items() if k != "effect"}], SCHEMA, "q")


@pytest.mark.parametrize("statement, message", [
    (law(["e9.9"]), "e9.9"),
    (law("e1.1"), "must be a list"),
    (law(["e1.1"])["law"], "wrap each law"),
])
def test_bad_theories_are_refused_before_saving(project, statement, message):
    local.write_records("paper-1", [dict(RECORD)], SCHEMA, "q")
    with pytest.raises(ValueError, match=message):
        local.write_theories([theory(statement)], "q")
    assert not th.Project.get_theory_store().theories


def test_papers_from_store_keeps_full_text_and_takes_a_limit_or_ids(project, tmp_path):
    path = tmp_path / "store.json"
    path.write_text(json.dumps({"paperstore": {
        "1": {"title": "One", "year": 2020, "paper_markdown": "# One\ntext", "status": "full-text"},
        "2": {"title": "Abstract only", "paper_markdown": "An abstract.", "status": "metadata-only"},
        "3": {"title": "Three", "publication_year": 2021, "paper_markdown": "# Three\ntext", "status": "full-text"},
        "4": {"title": "Four", "year": 2022, "paper_markdown": "# Four\ntext", "status": "full-text"},
    }}))
    assert local.papers_from_store(str(path), limit=2) == [
        {"paper_id": "1", "title": "One", "year": 2020, "markdown": "# One\ntext"},
        {"paper_id": "3", "title": "Three", "year": 2021, "markdown": "# Three\ntext"},
    ]
    assert list(json.loads((project / "paperstore.json").read_text())["paperstore"]) == ["1", "3"]
    assert [p["paper_id"] for p in local.papers_from_store(str(path), ids=[4, "2"])] == ["4"]


def test_save_theories_keeps_generator_and_model(project):
    uuid = local.write_records("paper-1", [dict(RECORD)], SCHEMA, "q")[0]["uuid"]
    generated = {"model": "gpt-x", "theory_response": {"theories_general": [theory(law([uuid]))], "theories_specific": []}}
    swept = {"model": "gpt-y", "theories": [{**theory(law([uuid])), "requested_output_type": "NULL RESULT"}]}
    ids = local.save_theories(generated, "q") + local.save_theories(swept, "q")
    store = th.Project.get_theory_store()
    assert [(store.theories[i].components["method"], store.theories[i].model_str) for i in ids] == [("accuracy", "gpt-x"), ("NULL RESULT", "gpt-y")]
    assert all(store.theories[i].supporting_evidence_ids for i in ids)
