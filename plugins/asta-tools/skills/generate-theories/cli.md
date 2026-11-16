# Theorizer with the CLI

You pay for it, through your own API key. It runs on this computer with `theorize`, which bakes in our preferences, and the model calls go to whoever your key is with. Nothing goes to Asta.

## Install

```bash
theorize --version        # already the version you were asked to use? skip the next line
uv tool install --upgrade --python 3.13 "asta-theorizer>=0.1.5" --with "pymupdf4llm<2"
theorize doctor
```

Keep the pins. 0.1.4 and older lack what this file uses, so the version pin makes an old one fail loudly. Without `--python`, uv builds on the newest Python, where one dependency has no prebuilt package and the install fails. `pymupdf4llm` 2.0 doesn't work with Theorizer, so without that pin PDFs come in with no text. `--upgrade` replaces whatever `theorize` is on PATH, so skip it when the installed version is the one you want.

## Keys

`theorize doctor` exits non-zero on anything that would stop a run, and says how to fix it.

- **OpenAI or Anthropic,** for the models. The fix that needs no restart: `mkdir -p ~/.config/asta && echo '{"openai": "..."}' > ~/.config/asta/api_keys.donotcommit.json` (or `"anthropic"`). A copy in the working directory, or `--key-dir DIR`, is read first. `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in the shell profile works for sessions started after it.
- **Mistral,** optional, for scanned PDFs (`--ocr mistral`).
- **Semantic Scholar** (`S2_API_KEY`), optional, for faster searches. Theorizer and `asta-papers` also read `SEMANTIC_SCHOLAR_API_KEY`; `s2` doesn't.

Never ask for a key in chat, because it would stay in the transcript. The person sets it.

## Models

The models follow the key, and `init` prints them. With an OpenAI key: `gpt-6-sol` for the once-per-run stages (plan, schemas, theories) and `gpt-6-luna` for the per-paper ones (extract, discover, import). With only an Anthropic key: `claude-opus-5-5` and `claude-sonnet-5-5`. OpenAI wins when both are set. `THEORIZER_MODEL` and `THEORIZER_EXTRACTION_MODEL` override them; so do `--model` and `--extraction-model` on `init`. Name the pair in the plan, change it only when the person asks, and never partway through a run.

## The stages

`<p>` is the project folder. Every command saves into it, so passes share one corpus and one theory store.

```bash
theorize -p <p> init
theorize -p <p> plan "<the question>" [--mission-statement "<mission>"]
theorize -p <p> load plan --key output.paper_search_query      # both must print something
theorize -p <p> load plan --key output.extraction_schema
# papers: papers.md
theorize -p <p> extract
theorize -p <p> theories generate [--mission-statement "<mission>"]
theorize -p <p> show theories
theorize -p <p> show theory-1          # one theory's laws, with the findings each cites
```

- **One command at a time per project.** A second one exits 3, "in use by another theorize command".
- **Ignore the hints `plan` prints** (an `s2 search … | theorize papers fetch -` line and `extract --max-papers 3`): papers come in as papers.md says, and extraction covers every paper.
- **`extract` exits 0 even when papers fail,** so read its output. It lists each paper whose model call gave up, with the reason (`timeout`, `error`, `prompt_too_long`, `unreadable_answer`, `interpreter_shutdown`). Rerun it whenever it lists one: it retries only those, and most succeed the second time. `--llm-timeout SECONDS` gives them longer. A "Could not convert response to JSON on first pass" warning is repaired by itself; "gave up" is the one to act on. Results are kept per paper, so a rerun after adding papers extracts only the new ones.
- **The evidence budget:** leave `--max-data-tokens` at its default (500,000), which fits every default model with room to spare. If `theories generate` prints "evidence subsampled to N%", it dropped the rest: run it again with `--objective attribution-batched` (not on `sweep`, which doesn't take it), which reads the rest in further batches. Rich schemas hit this well under 200 papers.
- **A generation that produces nothing** names the call that gave up. A call stopped by the model's safety filter answers with nothing: run it once more, and if it fails again, say which call.

**Refine,** from the same findings, with the person's direction:

```bash
theorize -p <p> theories generate --mission-statement "<the question, then their direction>" --save-as theories-refined-1
```

**Discover missed variables, then a pass per new schema.** List the first schema's fields with `show plan` and name them in the context:

```bash
theorize -p <p> discover --context "The first extraction already records: <its fields>. Propose variables it does not capture."
theorize -p <p> schemas from-discovery                       # prints schemas#0, schemas#1, ... (usually 2 to 4)
theorize -p <p> extract --schema schemas#0 --schema-id schema-2 --save-as extraction-schema-2
theorize -p <p> theories generate --extraction extraction-schema-2 --save-as theories-schema-2
```

Number the schema ids on from the first pass's `schema-1`, so each theory's evidence stays with its schema. The passes are independent; run them one after another.

**Sweep for a kind of statement** rather than general theories, for example the state of the literature or where results conflict:

```bash
theorize -p <p> theories sweep --output-types "<type>" --inference-types "<type>" --mission-statement "<mission>" --save-as <name>
theorize -p <p> show <name>
```

Output types include `STATE OF THE LITERATURE`, `APPRAISAL OF EVIDENCE QUALITY`, `CONTEXT DEPENDENCE`, `NULL RESULT` and `MECHANISTIC EXPLANATION`. Inference types include `CONTRAST ARGUMENT (HETEROGENEITY)`, `CRITICAL APPRAISAL OF THE EVIDENCE`, `ARGUMENT FROM ANALOGY` and `ABDUCTION (BEST EXPLANATION)`. Leave a flag out and it runs every type of that kind; `none` skips the kind. Each type costs about one generation. A sweep's statements are read by their save name.

**A second plan,** when a later step needs a field the first schema doesn't record: `plan ... --save-as plan-2`, check it the same way, then `extract --schema plan-2 --schema-id schema-b --save-as extraction-b` and `theories generate --extraction extraction-b`. It costs one more pass over every paper.

## The person's own papers

```bash
theorize -p <p> papers import <folder, files or a glob>      # .md, .txt and .pdf
theorize -p <p> show papers
```

Markdown is read as is. PDFs are converted on import; add `--ocr mistral` for scanned ones. Figures aren't read. Import spends one small model call per paper on metadata, so say the count in the plan.
