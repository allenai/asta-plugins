# Theorizer, local

On this computer, with the open-source Theorizer library. Nothing goes to Asta. With the person's model key, Theorizer's own stages run; with none, you read the papers and write the findings and theories yourself.

**Read Theorizer's guide first:** [AGENTS.md](https://github.com/allenai/asta-theorizer/blob/main/AGENTS.md) (plain text: `curl -sL https://raw.githubusercontent.com/allenai/asta-theorizer/main/AGENTS.md`). It has the calls, the shapes of papers, records and theories, and a worked example of each workflow. This file has only what joins it to Asta: the install, the keys, the papers, the folders the workspace site reads, and which part of the guide does each step.

## Install

In the project folder (the workspace's root):

```bash
uv venv --python 3.13
uv pip install "asta-theorizer>=0.2.0" "pymupdf4llm<2" "asta-papers[pymupdf,mistral]>=0.1.0"
```

Write each step as a short script in `<run>/scripts/` and run it with `.venv/bin/python <run>/scripts/<step>.py > <run>/theory/<step>.log 2>&1`, then read the log: the stages print a lot, and each prints its cost. To use [the glue](../scripts/theorizer_local.py), start the script with `import sys; sys.path.insert(0, "<this skill's folder>/scripts"); import theorizer_local as t`.

## Keys

`th.Config.init()` finds the key itself (the guide's Start): a key file `api_keys.donotcommit.json` (`{"openai": "..."}` or `{"anthropic": "..."}`) in the working folder or `~/.config/asta/`, else `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. A key file wins over the shell. The defaults are OpenAI models; with only an Anthropic key, set models as the guide's Models section says. Ask the person how to reach their key, and use only that. Never ask for the key in chat or print it.

**No key:** open the project with `t.open_without_keys("<run>/theory")` instead of `th.Config.init(...)`. It loads no key from the file or the shell, so a model stage called by mistake fails at once instead of spending. Call none of the stages the guide says call a model.

## Folders

```
<run>/
  searches/s1.json, s2.json, ...   each search, with its query
  papers.json                       the asta-papers store
  scripts/                          your step scripts
  theory/                           the Theorizer project: th.Config.init(project_dir="<run>/theory")
  data/                             what theorizer-site-data writes for the site
```

In a workflow, `<run>` is the run's folder (`.asta/flows/<NNNN>-<workflow>/`). After the papers, after each extraction and after each generation, write the site's data with `theorizer-site-data` (the run-workflow skill, Theory generation's "The run's page").

## Papers

```bash
Q='<the search query>'
.venv/bin/asta-papers search "$Q" --limit 100 | jq --arg q "$Q" '. + {query: $q}' > <run>/searches/s1.json
.venv/bin/asta-papers store --from-file <run>/searches/s1.json --limit <4 × the target> --require-full-text --into <run>/papers.json
```

- **The query.** With a key, start from the plan's `paper_search_query`; without, write one. Semantic Scholar matches every term, so keep it to 3 to 6 key terms, and cut a longer one that finds nothing. A query with an apostrophe goes in double quotes.
- **`--limit` is how many to try, not keep.** Often only 1 in 4 has full text. To top up, rerun `store` with a higher `--limit` (it skips papers it already has), or search again with other terms into `s2.json`.
- **Take the target** with `papers = t.papers_from_store("<run>/papers.json", limit=<target>)`: the first full-text papers in search order, added to the project's paperstore so the site shows their titles. Read the titles first; to drop an off-topic one, pass `ids=[<corpus ids>]` instead.
- **The person's own files:** `papers = t.add_papers(th.PaperImport.import_papers("<folder or glob>", read_metadata=<False with no key>)["papers"])` (the guide's Workflow 5). With no search, skip `searches/`.

## Each step, and where the guide covers it

Save every theory with the same question, the plan's `theory_request_normalized` (or, without a key, the question as the person wrote it), so the site shows them on one tab.

| Step | With a key | Without a key |
|---|---|---|
| Plan | `plan_theory_query(question, mission_statement=mission)`, Workflow 1. Check `["output"]` has `paper_search_query` and `extraction_schema`. A later script reads it back with `th.Project.load("plan-theory-query")["output"]` (Workflow 4). | Write the query and a schema of 4 to 8 slots yourself ("A schema slot"). |
| Extract | `extract_from_papers` then `flatten_records`, Workflow 1. Rerun the same call for `["failures"]`; it resumes. | Read each paper's `markdown` and write its records with `t.write_records` (Workflow 5). |
| Generate | `generate_theories(records, query, mission_statement=mission)`, then `t.save_theories(packed, query)`, which keeps the model and generator. | Write the theories; save them with `t.write_theories` (Workflow 5). |
| Refine with a mission (Theory generation 4a, a revision against verdicts, Data Driven's experiments, Secondary reproduction's verdicts) | `generate_theories` again from the same records with the mission ("A mission statement"); a mission meant to shape the search or schema goes on the plan, before extracting. | Write new theories that answer to the mission. |
| Discover variables (4b) | `discover_variables(papers, plan)`, then `make_schemas_from_variable_discovery`, Workflow 2 (a). For each new schema: `extract_from_papers(..., extraction_schema_id="schema-2")` (then `schema-3`, ...), generate from its records, save. | Read the papers for what the schema missed, write a new schema, and write each paper's records under `schema_id="schema-2"`. |
| Sweep by type (Gap-Driven's gap map and theories) | `generate_theories_over_types(records, query, output_types=[...], inference_types=[...])` ("Sweeping by type"), then `t.save_theories(packed, query)`. The names are in `th.Legacy.OUTPUT_TYPES` and `th.Legacy.INFERENCE_TYPES`; `[]` skips a kind. | Write theories of those kinds yourself. |

With a key you can still write theories yourself from the model's records: `t.records()` lists every record with its uuid and paper.

## Writing records and theories yourself

- **A record:** `name_short` (a few words), `name_full` (one line), `brief_description` (the finding, with its numbers), and one key per schema slot (`"not reported"` when the paper doesn't say). `write_records` checks the fields and gives each its `uuid`; a paper's records go in once per schema.
- **A theory:** `theory_name`, `theory_description` and `theory_statements`, each `{"law": {"statement_name", "theory_statement", "supporting_evidence": [{"text", "uuids": [...]}]}}`. The site also shows, when present: `theory_description_plain_language`, `new_predictions_likely`, `new_predictions_unknown`, `negative_experiments`, and on a law `theory_statement_plain_language`, `domain_scope`, `special_cases`, `conflicting_evidence` and `unaccounted_for`. `write_theories` refuses a law that cites a uuid no record has.
- **Subagents:** two at a time. Each writes its papers' records to `<run>/records/<paper_id>.json`, a JSON list of records, and this session writes them with `write_records`.
