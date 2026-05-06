---
name: Data Analysis
description: This skill should be used when the user asks to "analyze this dataset", "run datavoyager", "run data voyager", "explore this data", "what's in this CSV", "statistical analysis of", "find patterns in", or wants an AI-driven, code-executing analysis of a tabular dataset that answers a specific research question.
metadata:
  internal: true
allowed-tools:
  - Bash(asta auth login)
  - Bash(asta auth status)
  - Bash(asta analyze-data *)
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

**Never** ask the user to pre-upload the dataset. The skill handles the upload — see Step 4 — and the user just supplies the local file path.

## Step 3 — Optional interview (only when requested)

Fire one `AskUserQuestion` with:

1. **Question** — `<tightened>` vs `<alternative reframe>` (if you have one)
2. **Scope** — "focused (single hypothesis)" / "exploratory (multiple angles)"
3. **Extra context** — free-text "anything DataVoyager should know about the data?" (field meanings, known caveats)

Fold the answers back into the query string.

## Step 4 — Submit

The flow is two CLI calls under one **session UUID** (`$CTX`): `upload` writes the files to S3 under `context/$CTX/` and prints a structured JSON manifest; `send-message` submits the analysis with `--context-id $CTX` so the agent and any later resumption land in the same workspace.

```bash
CTX=$(python3 -c "import uuid; print(uuid.uuid4())")

# Upload — emits {"context_id": ..., "datasets": [{s3_uri, filename, ...}, ...]}
asta analyze-data upload --context-id "$CTX" ./sales.csv ./regions.csv \
  > "/tmp/analyze-data-$CTX-uploads.json"

# Build the agent payload from the upload manifest, then submit.
S3_URIS=$(python3 -c "
import json,sys
m=json.load(open(sys.argv[1]))
print(json.dumps([d['s3_uri'] for d in m['datasets']]))
" "/tmp/analyze-data-$CTX-uploads.json")

asta analyze-data send-message --context-id "$CTX" "$(python3 -c "
import json, os, sys
tool_request = {
    'query': sys.argv[1],
    'datasets': json.loads(sys.argv[2]),
}
# Pick the downstream modal app. Single dv-a2a-server fans out per-request to
# multiple modal envs (dv-core.rc, dv-core.prod, dv-core.<user>, ...). When
# unset, dv-core's ToolRequest field default applies (currently dv-core.rc).
if app := os.environ.get('ASTA_DV_MODAL_APP'):
    tool_request['modal_app_name'] = app
print(json.dumps({'kind': 'analyze-data', 'data': {'tool_request': tool_request}}))
" "<confirmed question>" "$S3_URIS")"
```

Capture `id` (task ID) and the echoed `contextId` from the response. The response's `contextId` will equal `$CTX` — keep both for resumption (Step 5 input-required, or follow-up runs that attach more files to the same session).

**Modal-app routing.** A single dv-a2a-server fans out per-request to one of several deployed DataVoyager modal apps (`dv-core.rc`, `dv-core.prod`, personal envs like `dv-core.<user>`). The skill omits `modal_app_name` unless `ASTA_DV_MODAL_APP` is set, so the field default in dv-core's `ToolRequest` schema applies (currently `dv-core.rc`). Set `ASTA_DV_MODAL_APP=dv-core.<user>` in your shell rc for personal-env testing, or `ASTA_DV_MODAL_APP=dv-core.prod` to route this skill against the prod backend.

**Resumability.** `$CTX` identifies the DataVoyager session. To attach more files later, run `upload --context-id $CTX <new-files>` (the new objects land alongside the existing ones under `context/$CTX/`) and then `send-message --context-id $CTX --task-id <existing> '<reply>'`. The user can also start a fresh session for the same datasets by minting a new `$CTX`; that gives a clean workspace and avoids cross-session collisions because S3 keys are namespaced per context.

## Step 5 — Poll

Don't foreground-poll in a loop (session blocks) and don't start individual `sleep 60`-then-check turns (harness blocks long leading sleeps). Instead, run the `poll` subcommand backgrounded — it exits on a terminal state and the harness will notify you when it finishes.

```bash
asta analyze-data poll "$TID" --output "/tmp/analyze-data-$TID.json"
```

Run with `run_in_background: true`. Status ticks go to stderr; the final Task JSON is written to `--output`. When the completion notification fires, read `/tmp/analyze-data-$TID.json` for the final payload.

While it's running, do not proactively check. Work on other things or wait — the notification is authoritative. If the user asks for a status check before the notification, only then tail the background task's stderr.

Terminal states:

- `completed` → Step 6
- `failed` → report `status.message` and stop
- `input-required` → relay to user, then `asta analyze-data send-message --task-id <ID> --context-id "$CTX" '<reply>'` and re-kick the polling loop

Runtime: highly variable (simple EDAs finish in a few minutes; multi-step modeling runs can take 20–40 min). Don't hard-fail before ~2 hours.

## Step 6 — Export and index

Hand off to the **Asta Artifacts** skill to export the task output (tables, plots, the notebook, any written analysis) and register each artifact with asta-documents. Pass `analyze-data` as the invoking skill and a slug derived from the analytical question; Asta Artifacts handles the path convention, manifest, and `index.yaml`.

## Step 7 — Summarize for the user

Present, in this order:

1. **Indexing + exploration paths** — one short block naming both ways to browse. Always include BOTH (the skill path for semantic search, the filesystem path for direct reading):

   > Indexed N artifacts in `.asta/analyze-data/<slug>/index.yaml`.
   > Explore via `asta documents search --summary='<concept>' --root=.asta/analyze-data/<slug>` or open the directory directly: `open <absolute-path-to-slug-dir>`

   Use the **absolute** path (e.g. `/Users/.../project/.asta/analyze-data/2026-04-23-…/`). Pick `<concept>` from a term central to the analysis (concrete, not generic — e.g. a column name, a model type).

2. **One-paragraph synthesis** — 2–4 sentences written fresh for this run. What's the headline finding? What did the data say vs. what did the user expect? Surface surprises, caveats, and whether the analysis answered the original question. This is discretionary — don't template it, read the output and synthesize.

3. **Table of key findings / charts** — one row per notable insight or figure: **finding** + **1–2 sentence detail** + (if applicable) **chart filename**.

Don't dump raw JSON. Don't repeat every step the agent took. Don't add a trailing "let me know if you'd like…" summary — the exploration block already tells the user how to keep going.

## References

- DataVoyager: <https://github.com/allenai/dv-core-asta-integration>
- A2A spec: <https://a2a-protocol.org/latest/specification/>
