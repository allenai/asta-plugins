---
name: Data Analysis
description: This skill should be used when the user asks to "analyze this dataset", "run datavoyager", "run data voyager", "explore this data", "what's in this CSV", "statistical analysis of", "find patterns in", or wants an AI-driven, code-executing analysis of a tabular dataset that answers a specific research question.
metadata:
  internal: true
allowed-tools:
  - Bash(asta auth login)
  - Bash(asta auth status)
  - Bash(asta data-analysis *)
  - Bash(asta artifacts *)
  - Bash(asta documents *)
  - Bash(open *)
---

# Data Analysis

Uses the [DataVoyager](https://github.com/allenai/dv-core-asta-integration) agent (hosted on Cloud Run, accessed via `asta-gateway`) to run a multi-agent data-science pipeline: the agent writes and executes code against the caller's dataset(s) in a sandboxed notebook and answers a research question. Auth is `asta auth login`.

## Step 1 — Draft a tightened query

**Before asking the user anything**, analyze their request and the surrounding context (current project, conversation history, files they've been working on) to produce a **tightened analytical question** that:

- Names the specific dataset(s) that will be analyzed
- States what decision or insight the user is after, not just "analyze X"
- Is phrased as a question DataVoyager can actually answer with code

Examples:

- User says "look at this CSV" → inspect the file path, sample the top rows if possible, produce a concrete query like "Which columns in `sales_q3.csv` have the strongest correlation with quarterly revenue, controlling for region?"
- User says "what's in the titanic data" → "What features best predict survival in `titanic.csv`, and how do survival rates differ across passenger class and sex?"
- User gives a specific question with a specific dataset → echo it verbatim

## Step 2 — Confirm with one chat question

In chat (not `AskUserQuestion`), present:

> Proposed analysis:
> - **Dataset(s)**: `<path>` *(will be uploaded to your DataVoyager workspace)*
> - **Question**: **`<tightened>`**
>
> You can:
> - Reply **yes** / **go** to run as-is
> - Reply with edits (e.g. *"focus on just Q3"*, *"ignore missing values"*) and I'll revise the question
> - *(Only if `AskUserQuestion` is available)* Reply **interview** to refine the question through a form

Only include the **interview** bullet when the `AskUserQuestion` tool is available.

Wait for the user's response. Paths:

1. **Affirmative** ("yes", "go", "proceed", "looks good") → Step 4.
2. **Natural-language edit** → update the question, re-show the same prompt.
3. **"Interview" / "refine"** → Step 3 *(AskUserQuestion required; if unavailable, ask in chat instead)*.

**Never** ask the user to pre-upload the dataset or paste an `<astaattachment>` tag. The `analyze` command handles the upload automatically — just pass the local path.

## Step 3 — Optional interview (only when requested)

Fire one `AskUserQuestion` with:

1. **Question** — `<tightened>` vs `<alternative reframe>` (if you have one)
2. **Scope** — "focused (single hypothesis)" / "exploratory (multiple angles)"
3. **Extra context** — free-text "anything DataVoyager should know about the data?" (field meanings, known caveats)

Fold the answers back into the query string.

## Step 4 — Submit

```bash
asta data-analysis analyze <local-path-or-paths> --query "<confirmed question>"
```

Multiple datasets are fine — pass each as a positional arg:

```bash
asta data-analysis analyze ./sales.csv ./regions.csv \
  --query "How do regional demographics correlate with sales performance?"
```

The CLI uploads each local file into the caller's workspace (via presigned S3 PUT), then submits the analysis. Capture the printed `task_id`.

## Step 5 — Poll

Don't foreground-poll in a loop (session blocks) and don't start individual `sleep 60`-then-check turns (harness blocks long leading sleeps). Instead, kick off **one** background polling loop that exits on a terminal state — the harness will notify you when it finishes.

```bash
TID="<TASK_ID>"
(
  while true; do
    resp=$(asta data-analysis task "$TID" 2>&1)
    state=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',{}).get('state','unknown'))" 2>/dev/null || echo parse_error)
    echo "[$(date +%H:%M:%S)] state=$state"
    case "$state" in
      completed|failed|input-required) printf '%s' "$resp" > "/tmp/data-analysis-$TID.json"; exit 0 ;;
      parse_error) exit 1 ;;
    esac
    sleep 60
  done
)
```

Run with `run_in_background: true`. When the completion notification fires, read `/tmp/data-analysis-$TID.json` for the final payload.

While it's running, do not proactively check. Work on other things or wait — the notification is authoritative. If the user asks for a status check before the notification, only then tail the background task's output file.

Terminal states:

- `completed` → Step 6
- `failed` → report `status.message` and stop
- `input-required` → relay to user, then `asta data-analysis send-message --task-id <ID> '<reply>'` and re-kick the polling loop

Runtime: highly variable (simple EDAs finish in a few minutes; multi-step modeling runs can take 20–40 min). Don't hard-fail before ~2 hours.

## Step 6 — Export and index

Hand off to the **Asta Artifacts** skill to export the task output (tables, plots, the notebook, any written analysis) and register each artifact with asta-documents. Pass `data-analysis` as the invoking skill and a slug derived from the analytical question; Asta Artifacts handles the path convention, manifest, and `index.yaml`.

## Step 7 — Summarize for the user

Present, in this order:

1. **Indexing + exploration paths** — one short block naming both ways to browse. Always include BOTH (the skill path for semantic search, the filesystem path for direct reading):

   > Indexed N artifacts in `.asta/data-analysis/<slug>/index.yaml`.
   > Explore via `asta documents search --summary='<concept>' --root=.asta/data-analysis/<slug>` or open the directory directly: `open <absolute-path-to-slug-dir>`

   Use the **absolute** path (e.g. `/Users/.../project/.asta/data-analysis/2026-04-23-…/`). Pick `<concept>` from a term central to the analysis (concrete, not generic — e.g. a column name, a model type).

2. **One-paragraph synthesis** — 2–4 sentences written fresh for this run. What's the headline finding? What did the data say vs. what did the user expect? Surface surprises, caveats, and whether the analysis answered the original question. This is discretionary — don't template it, read the output and synthesize.

3. **Table of key findings / charts** — one row per notable insight or figure: **finding** + **1–2 sentence detail** + (if applicable) **chart filename**.

Don't dump raw JSON. Don't repeat every step the agent took. Don't add a trailing "let me know if you'd like…" summary — the exploration block already tells the user how to keep going.

## References

- DataVoyager: <https://github.com/allenai/dv-core-asta-integration>
- A2A spec: <https://a2a-protocol.org/latest/specification/>
