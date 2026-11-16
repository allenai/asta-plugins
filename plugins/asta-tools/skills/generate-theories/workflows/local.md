# Theorizer, local

On this computer, with the library. Nothing goes to Asta. Two ways: `generate()` runs Theorizer's own stages with the person's model key; `write_records()` and `write_theories()` need no key, because you read the papers and write the findings and theories yourself.

```bash
uv venv --python 3.13 && uv pip install "asta-theorizer>=0.1.5" "pymupdf4llm<2" "asta-papers[pymupdf,mistral]>=0.1.0"
S=<this skill's folder>/scripts      # theorizer_local.py; run Python with .venv/bin/python, PYTHONPATH=$S
```

Keys: OpenAI or Anthropic in `~/.config/asta/api_keys.donotcommit.json` (`{"openai": "<key>"}`), or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`. Ask the person how to reach theirs; never ask for the key in chat.

## Papers

```bash
mkdir -p <run>/searches
Q='<the search query from the plan>'
.venv/bin/asta-papers search "$Q" --limit 100 > <run>/searches/s1.json
.venv/bin/asta-papers store --from-file <run>/searches/s1.json --limit <target> --require-full-text --into <run>/store.json
jq '.paperstore | length' <run>/store.json
```

Short queries: Semantic Scholar matches every term. Top up with another search until the store reaches the target. The person's own files: `papers_from_files("<folder or glob>")`.

## With a key

```python
import theorizer_local as t

t.open_project("<run>/theory")
plan = t.plan("<the question, as the person wrote it>", mission="<mission, or None>")
papers = t.papers_from_store("<run>/store.json")
out = t.extract(papers, plan)
print(len(out["records"]), out["failures"])        # rerun extract() on the failed papers
ids = t.generate(out["records"], plan, mission="<mission>")
ids += t.sweep(out["records"], plan, output_types=["STATE OF THE LITERATURE"], inference_types=[])   # [] skips a kind; None runs every type
```

## Without a key

```python
import theorizer_local as t

t.open_project("<run>/theory")
schema = [{"name": "<slot>", "type": "str", "description": "<what to record>"}]
for paper in t.papers_from_store("<run>/store.json"):
    records = [{"name_short": "...", "name_full": "...", "brief_description": "...", "<slot>": "..."}]   # from paper["markdown"]
    written = t.write_records(paper["paper_id"], records, schema, "<the question>")   # each now has its "uuid"
ids = t.write_theories([{
    "theory_name": "...", "theory_description": "...",
    "theory_statements": [{"law": {"statement_name": "...", "theory_statement": "...",
                                   "supporting_evidence": [{"text": "...", "uuids": ["<a record's uuid>"]}]}}],
}], "<the question>")
```

Read each paper yourself. Subagents: two at a time, each writing records to its own file that this session loads.
