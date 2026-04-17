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
  - Bash(asta documents *)
  - Bash(open *)
---

# Generate Theories

Uses the [Theorizer](https://github.com/allenai/asta-theorizer) agent (hosted on Cloud Run, accessed via `asta-gateway`) to search papers, extract evidence, form theories, and score their novelty. Auth is `asta auth login`.

## Step 1 — Draft a tightened query

**Before asking the user anything**, analyze their request and the surrounding context (current project, conversation history, files they've been working on) to produce a **tightened theory query** that:

- Has a specific phenomenon and domain
- Is phrased as a scientific question
- Reflects what the user is actually trying to understand

Examples:

- User says "generate theories for my project" → inspect the project, infer the research focus, produce a concrete query like "How do induction heads emerge during training in decoder-only transformers?"
- User says "theories about attention" → tighten to "What mechanisms drive attention head specialization during pretraining?"
- User gives a well-formed scientific question → echo it verbatim

## Step 2 — Confirm with one chat question

In chat (not `AskUserQuestion`), present:

> Proposed theory query: **`<tightened>`**
>
> I'll run 100 papers, accuracy-focused, with novelty assessment by default.
>
> You can:
> - Reply **yes** / **go** to run as-is
> - Reply with edits (e.g. *"focus more on training dynamics"*, *"broaden to multimodal"*) and I'll revise the query
> - *(Only if `AskUserQuestion` is available)* Reply **interview** to pick papers / objective / novelty via a form

Only include the **interview** bullet when the `AskUserQuestion` tool is available in the current environment. If it isn't, drop that bullet entirely — handle any parameter tuning via chat.

Wait for the user's response. Paths:

1. **Affirmative** ("yes", "go", "proceed", "looks good") → Step 4 with defaults.
2. **Natural-language edit** → update the query, re-show the same prompt.
3. **"Interview" / "refine parameters" / "ask me"** → Step 3 *(AskUserQuestion required; if unavailable, ask the parameter questions in chat instead)*.

**Novelty-focus shortcut:** If the user's original wording emphasizes novelty ("novel theories", "new theories we haven't seen", "find something surprising"), set `generation_objective: novelty-focused` without asking.

## Step 3 — Full interview (only when requested)

Fire one `AskUserQuestion` with:

1. **Query** — `<tightened>` vs `<creative reframe>` (if you have one)
2. **Papers** — `100 papers (~15–25 min)` / `30 papers (~7–12 min)` / `10 papers (fast, lower quality)`
3. **Objective** — `accuracy-focused` / `novelty-focused`
4. **Novelty assessment** — `Run novelty assessment (~$5–10, +30–60 min)` / `Skip`

⚠️ Novelty assessment is **~10× more expensive** than the rest of the pipeline (~$1/statement, $5–10 per 8-theory run) and adds **30–60 min**. Defaults include it because it's the most valuable output; only skip if the user wants fast iteration.

## Step 4 — Submit

```bash
asta generate-theories send-message '{
  "theory_query": "<confirmed>",
  "max_papers_to_retrieve": <n>,
  "generation_objective": "<accuracy-focused|novelty-focused>",
  "do_qualified_novelty_evaluation": <true|false>
}'
```

Capture `id` (task ID) and `contextId` from the response.

## Step 5 — Poll

Don't foreground-poll in a loop (session blocks) and don't start individual `sleep 60`-then-check turns (harness blocks long leading sleeps, and you'll forget to return). Instead, kick off **one** background polling loop that exits on a terminal state — the harness will notify you when it finishes.

```bash
TID="<TASK_ID>"
(
  while true; do
    resp=$(asta generate-theories task "$TID" 2>&1)
    state=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',{}).get('state','unknown'))" 2>/dev/null || echo parse_error)
    echo "[$(date +%H:%M:%S)] state=$state"
    case "$state" in
      completed|failed|input-required) printf '%s' "$resp" > "/tmp/theorizer-$TID.json"; exit 0 ;;
      parse_error) exit 1 ;;
    esac
    sleep 60
  done
)
```

Run with `run_in_background: true`. When the completion notification fires, read `/tmp/theorizer-$TID.json` for the final payload.

While it's running, do not proactively check. Work on other things or wait — the notification is authoritative. If the user asks for a status check before the notification, only then tail the background task's output file.

Terminal states:

- `completed` → Step 6
- `failed` → report `status.message` and stop
- `input-required` → relay to user, then `asta generate-theories send-message --task-id <ID> '<reply>'` and re-kick the polling loop

Runtime: ~10–30 min without novelty, +30–60 min with. Don't hard-fail before ~2 hours. If the background task itself dies (non-terminal exit), restart it once; if it dies again, surface the error.

## Step 6 — Export and index

Hand off to the **Asta Artifacts** skill to export the task output and
register each artifact with asta-documents. Pass `generate-theories` as the
invoking skill and a slug derived from the theory query; Asta Artifacts
handles the path convention, manifest, and index.yaml.

## Step 7 — Summarize for the user

Present, in this order:

1. **Indexing + exploration paths** — one short block naming both ways to browse. Always include BOTH (the skill path for semantic search, the filesystem path for direct reading):

   > Indexed N artifacts in `.asta/generate-theories/<slug>/index.yaml`.
   > Explore via `asta documents search --summary='<concept>' --root=.asta/generate-theories/<slug>` or open the directory directly: `open <absolute-path-to-slug-dir>`

   Use the **absolute** path (e.g. `/Users/.../project/.asta/generate-theories/2026-04-16-…/`) — the user may not be in this cwd when they click it. Pick `<concept>` from a term that appears across multiple theories (concrete, not generic).

2. **One-paragraph synthesis** — 2–4 sentences written fresh for this run. What do the theories collectively argue? Where do they converge, where do they diverge? What's the headline "so what"? This is discretionary — don't template it, read the theories and synthesize.

3. **Table of theories** — one row per theory: **name** + **2–3 sentence core idea**. Add a **novelty** column (headline degree) if novelty was scored.

Don't dump JSON. Don't repeat theory descriptions outside the table. Don't add a trailing "let me know if you'd like…" summary — the exploration block already tells the user how to keep going.

## References

- Theorizer: <https://github.com/allenai/asta-theorizer>
- Paper (*Generating Literature-Driven Scientific Theories at Scale*): <https://arxiv.org/abs/2601.16282>
- A2A spec: <https://a2a-protocol.org/latest/specification/>
