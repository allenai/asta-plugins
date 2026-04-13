---
name: Generate Theories
description: This skill should be used when the user asks to "generate theories", "theorize about", "what theories explain", "form scientific theories", "literature-driven theories", "hypothesize", "form hypotheses", "generate hypotheses", "what hypotheses explain", "run the theorizer", or wants AI-generated, literature-grounded scientific theories or hypotheses about a research question.
metadata:
  internal: true
allowed-tools:
  - Bash(asta auth login)
  - Bash(asta auth status)
  - Bash(asta generate-theories *)
  - Bash(asta artifacts *)
  - Bash(open *)
---

# Generate Theories

Uses the [Theorizer](https://github.com/allenai/asta-theorizer) agent to search papers, extract evidence, form theories, and (optionally) score their novelty. Auth is the standard `asta auth login` flow; gateway URL is overridable via `ASTA_GATEWAY_URL`.

## Quick path — skip all elicitation

If the user says "skip elicitation" or similar ("just run it", "go", "use defaults"), do NOT call `AskUserQuestion`. Submit their query verbatim plus any parameters they explicitly mentioned; let Theorizer's own defaults fill in the rest. Jump to Step 4.

## Steps 1–3 — Single interview

Before calling `AskUserQuestion`, silently draft:
- A *slightly* tighter version of the user's query (same intent, sharper phrasing — skip if near-identical to verbatim)
- An optional creative reframing (skip unless you have a genuinely different angle)
- A mission statement: "I want to understand X so that I can Y" (best-effort; the Y part will often be wrong — that's fine)

Then fire **one** `AskUserQuestion` with all of the following questions:

1. **Query** — options: `<verbatim>` / `<tightened>` (if different) / `<creative>` (if warranted)
2. **Mission statement** — options: `Skip — no goal frame` / `<your drafted sentence>`
3. **Papers** — options: `100 papers (~15–25 min)` / `30 papers (~7–12 min)`
4. **Objective** — options: `accuracy-focused` / `novelty-focused`
5. **Novelty assessment** — options: `Skip` / `Run novelty assessment (~$5–10, +30–60 min)`

⚠️ Novelty assessment is **~10× more expensive** than the rest of the pipeline (~$1/statement, $5–10 per 8-theory run) and adds **30–60 min** wall-clock. Only enable when the user is fully clear they want it.

**Trust user choices.** Don't re-confirm unusual-but-valid values in a second modal (1-paper runs, novelty-focused + novelty-off, etc.). Only re-prompt when input is literally invalid (zero/negative, empty query), and do so in chat.

## Step 4 — Submit

```bash
asta generate-theories send-message '{
  "theory_query": "<confirmed>",
  "max_papers_to_retrieve": <n>,
  "generation_objective": "<accuracy-focused|novelty-focused>",
  "do_qualified_novelty_evaluation": <true|false>
}'
```

Add `"mission_statement"` / any power-user overrides (`model_str_primary`, etc.) if the user mentioned them. `asta generate-theories card` enumerates all parameters.

Capture `id` (task ID) and `contextId` from the response.

> Note: bring-your-own paperstore is not yet supported — Theorizer always searches literature from scratch in v1.

## Step 5 — Poll

```bash
asta generate-theories task "<TASK_ID>"
```

Poll every ~60s. **Do not use an inline `sleep 60 && …` — it will be blocked.** Either run the poll loop with `run_in_background: true` so the sleep happens in a background shell, or just re-issue the one-shot poll command periodically without an explicit sleep (you can interleave other work between polls).

Surface step transitions to the user (search → extract → form theories → novelty). `status.state`:
- `submitted` / `working` → keep polling
- `completed` → Step 6
- `failed` → report `status.message` and stop
- `input-required` → relay to user, then `asta generate-theories send-message --task-id <ID> '<reply>'`

Runtime: ~10–30 min without novelty, +30–60 min with. Tasks can occasionally run beyond an hour; don't hard-fail before ~2 hours.

`artifacts[]` accumulate as the pipeline runs. **On the first poll where `artifacts[]` is non-empty (usually the Extraction Schema in the first minute or two), tell the user once in chat that they can ask at any time to preview what's been generated so far — the Asta Artifacts skill can export partial data mid-run.** Don't repeat this on every subsequent poll.

## Step 6 — Summarize

Present a markdown table with one row per theory: **name** and a **2–3 sentence description**. Add a headline novelty column if novelty was scored. Don't dump JSON.

## Step 7 — Export

Ask the user if they want a full report (default yes). If yes, hand off to the **Asta Artifacts** skill — it handles HTML and Markdown export and knows the full workflow.

## References

- A2A spec: <https://a2a-protocol.org/latest/specification/>
- Theorizer: <https://github.com/allenai/asta-theorizer>
- Paper (*Generating Literature-Driven Scientific Theories at Scale*): <https://arxiv.org/abs/2601.16282>
- asta-gateway: <https://github.com/allenai/asta-gateway>
