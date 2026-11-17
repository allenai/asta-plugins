"""Theorizer, local: the glue between the Theorizer library and an Asta workspace.

The library does the work; its guide is https://github.com/allenai/asta-theorizer/blob/main/AGENTS.md.
This adds only what the guide can't know:

    open_without_keys(project)          open a project with no model key loaded, so no stage can call a model
    papers_from_store(path, limit, ids) the full-text papers of an `asta-papers store` file, added to the project's paperstore
    add_papers(papers)                  the library's papers (PaperImport.import_papers) into the project's paperstore
    save_theories(packed, question)     a generation's theories into the theory store, with their generator and model
    write_records(paper_id, records, schema, question)   one paper's records, written by you, once
    records()                           every record in the project, with its uuid and paper
    write_theories(theories, question)  theories you wrote, refused if a law cites a uuid no record has

The workspace's theory page reads paperstore.json for the papers' titles, and each theory's method
and model_str for its generator and model.
"""

from __future__ import annotations

import json
import os
import sys

import theorizer as th

RECORD_FIELDS = ("name_short", "name_full", "brief_description")


def open_without_keys(project: str) -> None:
    """Open the project with no model key: none from the person's key file, none from the shell.
    A model stage called by mistake then fails at once instead of spending."""
    for name in list(th.Config.KEY_ENV_VARS.values()) + ["LITELLM_BASE_URL", "LITELLM_USER_KEY"]:
        os.environ.pop(name, None)
    th.Config.USER_CONFIG_DIR = os.path.join(os.path.abspath(project), ".no-user-keys")
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


def papers_from_store(path: str, limit: int | None = None, ids: list | None = None) -> list:
    """The full-text papers of an `asta-papers store` file, in store order (the search's), as the
    library's papers. `limit` keeps the first N; `ids` keeps only those corpus ids, in that order.
    Only the papers returned go into the project's paperstore."""
    with open(path) as f:
        doc = json.load(f)
    entries = doc.get("paperstore") or {}
    full = {k: p for k, p in entries.items() if p.get("status") == "full-text" and (p.get("paper_markdown") or "").strip()}
    if ids is not None:
        wanted = [str(i) for i in ids]
        missing = [i for i in wanted if i not in full]
        if missing:
            print(f"papers_from_store(): no full text in {path} for {', '.join(missing)}", file=sys.stderr)
        full = {k: full[k] for k in wanted if k in full}
    if limit is not None:
        full = dict(list(full.items())[:limit])
    _keep(full, {a: k for a, k in (doc.get("paperstore_lut") or {}).items() if k in full})
    return [
        {"paper_id": k, "title": p.get("title"), "year": p.get("year") or p.get("publication_year"), "markdown": p["paper_markdown"]}
        for k, p in full.items()
    ]


def add_papers(papers: list) -> list:
    """Papers from `th.PaperImport.import_papers(...)["papers"]` (the person's files) into the
    project's paperstore, so the site shows their titles. Returns them unchanged."""
    _keep({
        p["paper_id"]: {"title": p.get("title"), "year": p.get("year"), "paper_markdown": p.get("markdown") or "",
                        "status": "full-text" if (p.get("markdown") or "").strip() else "metadata-only", "source_file": p.get("source_file"),
                        "s2_metadata": {"title": p.get("title"), "year": p.get("year"), "abstract": p.get("abstract"), "venue": p.get("venue"),
                                        "authors": [{"name": n} for n in (p.get("authors") or []) if n]}}
        for p in papers if p.get("paper_id")
    })
    return papers


def _register(theories: list, question: str, method: str | None, model: str | None) -> list:
    store = th.Project.get_theory_store()
    before = set(store.theories)
    th.Pipeline.to_theorystore([t for t in theories if isinstance(t, dict)], question, model_str=model, method=method)
    return [tid for tid in store.theories if tid not in before]


def save_theories(packed: dict, question: str, method: str | None = None) -> list:
    """What `generate_theories()` or `generate_theories_over_types()` returned, into the theory
    store with the model that wrote them. A generation's method is "accuracy" unless you pass its
    objective; a sweep's theories keep the type each was asked for. Returns the new theory ids.
    Theories saved with the same `question` share a tab on the page."""
    found = packed.get("theory_response")
    if isinstance(found, dict):
        theories = (found.get("theories_general") or []) + (found.get("theories_specific") or [])
        method = method or "accuracy"
    else:
        theories = packed.get("theories") or []
    if not theories:
        print("save_theories(): this result has no theories", file=sys.stderr)
    return _register(theories, question, method, packed.get("model"))


def write_records(paper_id: str, records: list, schema: list, question: str, schema_id: str = "schema-1") -> list:
    """One paper's records, written by you: each has name_short, name_full, brief_description and
    one key per schema slot. Returns them with the uuid each law cites. A paper's records are
    written once per schema; a second call returns the first call's records and says so."""
    slots = tuple(s["name"] for s in schema)
    for i, record in enumerate(records):
        missing = [k for k in RECORD_FIELDS + slots if k not in record]
        if missing:
            raise ValueError(f"{paper_id} record {i}: missing {', '.join(missing)}")
    store = th.Project.get_theory_store()
    if schema_id not in store.extraction_schemas:
        store.add_extraction_schema(
            th.Legacy.ExtractionQuerySchema(schema=schema, extraction_query=question, supporting_theory_ids=[], id=schema_id, model_str="written")
        )
    for result in store.extraction_results.values():
        if result.paper_id == paper_id and result.extraction_schema_id == schema_id:
            print(f"write_records(): {paper_id} already has records under {schema_id}; returning those", file=sys.stderr)
            return result.extracted_data
    result_id = store.add_extraction_result(
        th.Legacy.ExtractionQueryResult(
            paper_id=paper_id, extraction_schema_id=schema_id, extracted_data=records, potentially_relevant_new_papers=[], model_str="written"
        )
    )
    th.Project.save_theory_store()
    return store.extraction_results[result_id].extracted_data


def records(schema_id: str | None = None) -> list:
    """Every record in the project, yours or a model's, each with its uuid, paper_id, paper_title and schema_id."""
    titles = {k: (p or {}).get("title") for k, p in th.Project.get_paper_store().paperstore.items()}
    out = []
    for result in th.Project.get_theory_store().extraction_results.values():
        if schema_id is not None and result.extraction_schema_id != schema_id:
            continue
        for record in result.extracted_data or []:
            if isinstance(record, dict):
                out.append({**record, "paper_id": result.paper_id, "paper_title": titles.get(result.paper_id), "schema_id": result.extraction_schema_id})
    return out


def _cited(node) -> set:
    if isinstance(node, dict):
        return set(node.get("uuids") or []) | {u for k, v in node.items() if k != "uuids" for u in _cited(v)}
    if isinstance(node, list):
        return {u for v in node for u in _cited(v)}
    return set()


def write_theories(theories: list, question: str) -> list:
    """Theories you wrote. Each law is wrapped, {"law": {...}}, and each piece of evidence is
    {"text": ..., "uuids": [<record uuids>]}. Refused before anything is saved if a law isn't
    wrapped, a `uuids` isn't a list, or a uuid matches no record. Returns the new theory ids."""
    for t in theories:
        for i, s in enumerate(t.get("theory_statements") or []):
            if not (isinstance(s, dict) and isinstance(s.get("law"), dict)):
                raise ValueError(f"{t.get('theory_name')!r} statement {i}: wrap each law as {{\"law\": {{...}}}}")
            for kind in ("supporting_evidence", "conflicting_evidence", "unaccounted_for"):
                for ev in s["law"].get(kind) or []:
                    if isinstance(ev, dict) and not isinstance(ev.get("uuids", []), list):
                        raise ValueError(f"{t.get('theory_name')!r} statement {i} {kind}: uuids must be a list")
    unknown = _cited(theories) - {r.get("uuid") for r in records()}
    if unknown:
        raise ValueError("uuids no record has: " + ", ".join(sorted(unknown)))
    return _register(theories, question, "written", "written")
