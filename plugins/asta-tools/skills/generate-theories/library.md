# Theorizer with the library

You pay for it, through your coding agent. You do the model's part: read the papers, write the findings, write the theories. The library gives you the types and the ids, refuses a citation that doesn't resolve, and writes the same project a CLI run does, so `theorize show theories`, `theorize export html` and the workspace's pages all work on it.

```bash
uv venv --python 3.13 && uv pip install "asta-theorizer>=0.1.5" "pymupdf4llm<2"
.venv/bin/theorize guide   # Workflow 5 is this one, with an example that runs as written
```

Each shell command starts fresh, so call the venv's own `.venv/bin/theorize` and `.venv/bin/python` rather than activating it.

- **Open the project offline:** `th.Config.init(project_dir="<p>", offline=True)`. No model key is loaded, so a call that would reach a model fails instead of spending. Use the same folder for `theorize -p <p>`.
- **The shapes:** `theorize guide --schema record` and `--schema theory` (also `paper` and `schema_slot`).
- **Papers,** with the CLI, which calls no model here: `theorize -p <p> papers import --no-metadata <files>` for the person's own, or `theorize -p <p> papers fetch <corpus ids>` for open-access ones (Semantic Scholar corpus ids, from `s2`). Then `th.Project.load("papers")` gives you each paper's `paper_id`, title and markdown.
- **Your findings:** `th.add_records(paper_id, records, extraction_schema=schema)` checks each record against the schema (null for a slot the paper doesn't report; no slots it doesn't have), saves the schema, and returns the records with the `uuid` each law cites.
- **Your theories:** `th.add_theories(theories, query, extraction_schema=schema)` refuses a law that cites no record, or cites an id no record has, and returns the new theory ids.
- **Each call adds.** Running one again adds the same records or theories again.
- **Output:** `theorize -p <p> export html`, and `th.check_evidence()` for the counts.

Read each paper yourself. You don't need a subagent per paper; keep going in one session, saving as you go.
