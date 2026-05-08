---
name: Experiment Designer
description: This skill should be used when the user asks to "design an experiment", "plan an experiment", "experimental design", "design a study", or wants a detailed, literature-grounded computational experiment plan for testing a research question, theory, or hypothesis.
metadata:
  internal: true
allowed-tools:
  - Bash(asta auth login)
  - Bash(asta auth status)
  - Bash(asta auto-exp-designer *)
  - Bash(asta artifacts *)
  - Bash(asta documents *)
  - Bash(open *)
---

# Experiment Designer

Hands a research question to the [Auto Experiment Designer](https://github.com/allenai/auto-experiment-designer) agent (via `asta-gateway`). It reads the literature, looks at prior designs, and writes back an HTML report with a proposed experiment. Auth: `asta auth login`.

The CLI is generated from the agent card. Discover the surface yourself:

- `asta auto-exp-designer --help` — list subcommands.
- `asta auto-exp-designer card` — full agent card.
- `asta auto-exp-designer describe design-experiment` — input schema.

## Submit

```bash
asta auto-exp-designer design-experiment \
    --query "<research question>" \
    [--max-papers-per-item 5]
```

The CLI polls to completion (5s/15s/60s backoff) and prints the final Task JSON to stdout. Run with `Bash(..., run_in_background=true)` and wait for the completion notification — don't sit in a poll loop. Use `--no-wait` only if the user asked for fire-and-forget.

## Drafting the query

The downstream agent picks the models, datasets, and metrics itself. Don't pre-fill them. If the user said "experiment about ReAct," let the agent decide whether to use TextWorld or ALFWorld — don't decide for them that we're using GPT-4 with a 5% threshold.

A good rule: if you're about to add a model name, a benchmark name, or a number, stop and ask whether the user actually told you that. If not, leave it out. The agent does worse with invented specifics it has to either honor or work around.

If the user's request is clear, submit directly. If it's vague (e.g. "design an experiment for my project"), read the repo first — README, recent commits, files they've been editing — then write the question grounded in that. If you still can't tighten it, fire one `AskUserQuestion` with 2–3 candidate framings.

## Defaults worth knowing

Schema defaults — don't repeat them unless the user wants to tune:

- `max_papers_per_item`: 5 (~45 min, ~$5). Bump for broader literature coverage; lower for a faster, narrower design.

## After the task completes

Hand off to the **Asta Artifacts** skill to export and index the result — it owns the path convention, manifest, and asta-documents registration. Pass `auto-exp-designer` as the invoking skill and a slug shaped `YYYY-MM-DD-<short-query-slug>` derived from the query (e.g. `2026-05-08-react-split-vs-combined`).

Then open the HTML and write, in chat, in this order:

1. **Open the report**:

   ```bash
   open <abs path>/index.html
   ```

2. **Where it lives**:

   > Indexed N artifacts in `.asta/auto-exp-designer/<slug>/index.yaml`.
   > Search with `asta documents search --summary='<concept>' --root=.asta/auto-exp-designer/<slug>`, or open the folder: `open <abs slug dir>`

   Use absolute paths. Pick `<concept>` from a term central to the design.

3. **Summary** — 2–4 fresh sentences on what the design proposes. What's the experiment? What's it varying? What's it measuring? Read `experiment_name`, `experiment_description`, `plain_language_description` and write fresh — don't template, don't copy the plain-language description verbatim.

4. **Table of aspects** — one row per item in `recipe_to_implement[]`: aspect name + a short sentence on what it's for. Add a *relevance* column if `relevance` is set.

No "let me know if you'd like…" tail — the search/open links cover it.

## Resumption / errors

- `state=input-required` → CLI prints a `Continue with: …` hint. Relay to the user; resend with `asta auto-exp-designer send-message --task-id <id> --context-id <ctx> '<reply>'`.
- `state=failed` → report `status.message` and stop.
- Network/protocol errors exit non-zero with a JSON `{error: …}` on stderr.

Runs usually take 30–60 minutes. Don't give up before 90.

## References

- Auto Experiment Designer: <https://github.com/allenai/auto-experiment-designer>
- Agent card / schemas: `asta auto-exp-designer card` / `asta auto-exp-designer describe design-experiment`
- A2A spec: <https://a2a-protocol.org/latest/specification/>
