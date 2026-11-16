"""Theorizer, local: the library on this computer.

generate() and sweep() call a model with the person's key. write_records() and write_theories() call
none: the agent reads the papers and writes the findings and theories itself.
"""

from __future__ import annotations

import json

import theorizer as th


def open_project(project: str) -> None:
    th.Config.init(project_dir=project)


def _keep(entries: dict, lut: dict | None = None) -> None:
    """Into the project's paperstore.json, which the site reads; papers already there stay."""
    store = th.Project.get_paper_store()
    for key, paper in entries.items():
        if isinstance(paper, dict) and key not in store.paperstore:
            store.paperstore[key] = paper
            store.paperstore_lut[key] = key
    for alt, key in (lut or {}).items():
        store.paperstore_lut.setdefault(alt, key)
    th.Project.save_paper_store()


def papers_from_store(path: str) -> list:
    """An `asta-papers store` file, as the papers extraction takes. Full text only."""
    with open(path) as f:
        doc = json.load(f)
    full = {k: p for k, p in doc["paperstore"].items() if (p.get("paper_markdown") or "").strip()}
    _keep(full, {a: k for a, k in (doc.get("paperstore_lut") or {}).items() if k in full})
    return [{"paper_id": k, "title": p.get("title"), "year": p.get("publication_year"), "markdown": p["paper_markdown"]} for k, p in full.items()]


def papers_from_files(paths, read_metadata: bool = True) -> list:
    """The person's .md, .txt or .pdf files. read_metadata spends one small model call per paper."""
    papers = th.PaperImport.import_papers(paths, read_metadata=read_metadata)["papers"]
    _keep({
        p["paper_id"]: {"title": p.get("title"), "publication_year": p.get("year"), "paper_markdown": p.get("markdown") or "",
                        "status": "full-text" if (p.get("markdown") or "").strip() else "metadata-only", "source_file": p.get("source_file"),
                        "s2_metadata": {"title": p.get("title"), "year": p.get("year"), "abstract": p.get("abstract"), "venue": p.get("venue"),
                                        "authors": [{"name": n} for n in (p.get("authors") or []) if n]}}
        for p in papers if p.get("paper_id")
    })
    return papers


def plan(question: str, mission: str | None = None) -> dict:
    out = th.Pipeline.plan_theory_query(question, mission_statement=mission)["output"]
    if not (out.get("paper_search_query") and out.get("extraction_schema")):
        raise RuntimeError("empty plan: run plan() again")
    return out


def extract(papers: list, the_plan: dict, schema: list | None = None, schema_id: str = "schema-1") -> dict:
    """Returns {"records", "failures"}. Rerun with the failed papers: most succeed the second time."""
    packed = th.Pipeline.extract_from_papers(
        papers, the_plan["extraction_query"], schema or the_plan["extraction_schema"], extraction_schema_id=schema_id
    )
    return {"records": th.Pipeline.flatten_records(packed), "failures": packed.get("failures") or []}


def _register(theories: list, question: str, method: str) -> list:
    store = th.Project.get_theory_store()
    before = set(store.theories)
    th.Pipeline.to_theorystore([t for t in theories if isinstance(t, dict)], question, method=method)
    return [tid for tid in store.theories if tid not in before]


def generate(records: list, the_plan: dict, mission: str | None = None) -> list:
    response = th.Pipeline.generate_theories(records, the_plan["theory_request_normalized"], mission_statement=mission)
    found = response["theory_response"]
    return _register(found.get("theories_general", []) + found.get("theories_specific", []), the_plan["theory_request_normalized"], "generate")


def sweep(records: list, the_plan: dict, output_types=None, inference_types=None, mission: str | None = None) -> list:
    packed = th.Pipeline.generate_theories_over_types(
        records, the_plan["theory_request_normalized"], output_types=output_types, inference_types=inference_types, mission_statement=mission
    )
    return _register(packed.get("theories") or [], the_plan["theory_request_normalized"], "sweep")


def write_records(paper_id: str, records: list, schema: list, question: str, schema_id: str = "schema-1") -> list:
    """One paper's records, once. Returns them with the uuid each law cites."""
    store = th.Project.get_theory_store()
    if schema_id not in store.extraction_schemas:
        store.add_extraction_schema(
            th.Legacy.ExtractionQuerySchema(schema=schema, extraction_query=question, supporting_theory_ids=[], id=schema_id, model_str="written")
        )
    for result in store.extraction_results.values():
        if result.paper_id == paper_id and result.extraction_schema_id == schema_id:
            return result.extracted_data
    result_id = store.add_extraction_result(
        th.Legacy.ExtractionQueryResult(
            paper_id=paper_id, extraction_schema_id=schema_id, extracted_data=records, potentially_relevant_new_papers=[], model_str="written"
        )
    )
    th.Project.save_theory_store()
    return store.extraction_results[result_id].extracted_data


def _cited(node) -> set:
    if isinstance(node, dict):
        return set(node.get("uuids") or []) | {u for k, v in node.items() if k != "uuids" for u in _cited(v)}
    if isinstance(node, list):
        return {u for v in node for u in _cited(v)}
    return set()


def write_theories(theories: list, question: str) -> list:
    """Theories whose laws ({"law": {...}}) cite records already written. Refuses an unknown uuid."""
    store = th.Project.get_theory_store()
    known = {r.get("uuid") for res in store.extraction_results.values() for r in (res.extracted_data or []) if isinstance(r, dict)}
    unknown = _cited(theories) - known
    if unknown:
        raise ValueError("uuids no record has: " + ", ".join(sorted(unknown)))
    return _register(theories, question, "written")

