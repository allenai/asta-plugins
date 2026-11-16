# Theorizer with the library

You pay for it, through your coding agent. You do the model's part: read the papers, write the findings, write the theories. The library's store gives each finding the id a law cites and writes the same project a CLI run does, so `theorize show theories`, `theorize export html` and the workspace's pages all work on it. No model key is needed.

```bash
uv venv --python 3.13 && uv pip install "asta-theorizer>=0.1.5" "pymupdf4llm<2"
```

Each shell command starts fresh, so call the venv's own `.venv/bin/theorize` and `.venv/bin/python` rather than activating it.

**Papers,** with the CLI, which calls no model here: `theorize -p <p> papers import --no-metadata <files>` for the person's own, or `theorize -p <p> papers fetch <corpus ids>` for open-access ones (Semantic Scholar corpus ids, from `s2`). Use the same folder `<p>` below.

```python
import theorizer as th

th.Config.init(project_dir="<p>")
store = th.Project.get_theory_store()
papers = th.Project.get_paper_store().paperstore      # {paper_id: {"title", "paper_markdown", ...}}

schema = [{"name": "study_species", "type": "str", "description": "The species studied"}]   # the plan's schema
store.add_extraction_schema(th.Legacy.ExtractionQuerySchema(
    schema=schema, extraction_query="<the question>", supporting_theory_ids=[], id="schema-1", model_str="written"))

# One call per paper, once: each call adds its records again.
result_id = store.add_extraction_result(th.Legacy.ExtractionQueryResult(
    paper_id=paper_id, extraction_schema_id="schema-1", extracted_data=records,
    potentially_relevant_new_papers=[], model_str="written"))
records = store.extraction_results[result_id].extracted_data   # now each has the "uuid" a law cites
th.Project.save_theory_store()

stored = th.Pipeline.to_theorystore(theories, "<the question>", model_str="written", method="written")
print(list(stored["theories"]))                       # theory-1, ...; the store is saved
```

- **A record:** `name_short`, `name_full`, `brief_description`, then one key per schema slot (null for what the paper doesn't report).
- **A theory:** `theory_name`, `theory_description`, and `theory_statements`, each law wrapped as `{"law": {"statement_name", "theory_statement", "supporting_evidence": [{"text", "uuids"}]}}`. Every optional field is in the engine's own prompt, `theorizer/_engine/src/TheorizerProcessing.py` in the installed package.
- **Check the citations yourself** before `to_theorystore`: every uuid a law cites must be a record's. A uuid no record has links to nothing, and nothing says so.
- **Output:** `theorize -p <p> show theory-1` and `theorize -p <p> export html`.

Read each paper yourself. You don't need a subagent per paper; keep going in one session, saving as you go. With subagents, run two at a time, give each its own folder, and have them write records to files that this session loads.
