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

Hands a research question to the [Auto Experiment Designer](https://github.com/allenai/auto-experiment-designer) agent. It reads the literature, looks at prior designs, and writes back an HTML report with a proposed experiment. Run `asta auth login` first.

## Step 1 — Figure out what the user actually wants to study

Before drafting anything, look around for context:

- Read the repo's README and any docs that look relevant
- Skim the recent conversation
- Check what files the user has been editing (`git status`, recent commits)

Then write a short research question — one or two sentences — that captures what they're trying to learn. Stay close to how *they* phrased it.

The downstream agent picks the models, datasets, and metrics itself. That's its job. So don't pre-fill them. If the user said "experiment about ReAct," ask whether splitting think and act prompts helps — don't decide for them that we're using GPT-4 on TextWorld with a 5% threshold.

A good rule: if you're about to add a model name, a benchmark name, or a number, stop and ask whether the user actually told you that. If not, leave it out. The agent does worse with invented specifics it has to either honor or work around.

If the request is vague and you can't tighten it without guessing, ask one short clarifying question instead.

Examples:

- *"experiment about ReAct"* → *"Does splitting a ReAct agent into separate think and act prompts work better than the standard combined prompt?"*
- *"design an experiment for my project"* → read the repo first, then write the question grounded in what the project is doing
- A clear research question → use it as-is

## Step 2 — Confirm the question with the user

In chat, show them what you've got:

> Proposed experiment query: **`<your draft>`**
>
> I'll run with `max_papers_per_item=5` (the default). It takes about 45 minutes and costs around $5.
>
> Reply **yes** to run it, or tell me what to change. Say **fewer papers** or **more papers** if you want to adjust speed vs. breadth.

Wait for them. If they say yes, go to step 3. If they edit it, revise and re-show. If they ask for more or fewer papers, use that value.

Don't ask about `max_papers_per_item` unless they bring it up.

## Step 3 — Send it

```bash
asta auto-exp-designer send-message '{
  "query": "<confirmed>",
  "max_papers_per_item": <n>
}'
```

Leave `max_papers_per_item` out if you're using the default. Save the `id` and `contextId` from the response.

## Step 4 — Wait for it to finish

Don't sit and poll in a loop, and don't do `sleep 60` between turns — the harness will block it and you'll lose the thread. Run one background loop that exits when the task is done. The harness will ping you when it finishes.

```bash
TID="<TASK_ID>"
(
  while true; do
    resp=$(asta auto-exp-designer task "$TID" 2>&1)
    state=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',{}).get('state','unknown'))" 2>/dev/null || echo parse_error)
    echo "[$(date +%H:%M:%S)] state=$state"
    case "$state" in
      completed|failed|input-required) printf '%s' "$resp" > "/tmp/auto-exp-designer-$TID.json"; exit 0 ;;
      parse_error) exit 1 ;;
    esac
    sleep 60
  done
)
```

Run it with `run_in_background: true`. When the notification fires, read `/tmp/auto-exp-designer-$TID.json` for the final result.

While it's running, work on something else. Don't go check on it. If the user asks for an update before the notification, then you can peek.

What can come back:

- `completed` — go to step 5
- `failed` — show them `status.message` and stop
- `input-required` — relay the question, get their reply, send it back with `asta auto-exp-designer send-message --task-id <ID> '<reply>'`, and restart the wait loop

Runs usually take 30–60 minutes. Don't give up before 90.

## Step 5 — Export and open the report

The agent returns one artifact with three pieces: the structured design as JSON, a standalone HTML report, and a plain-language summary. The HTML is what the user actually wants to look at. Export it and open it in the browser:

```bash
TASK_DIR=$(mktemp -d)
cp "/tmp/auto-exp-designer-$TID.json" "$TASK_DIR/task.json"

SLUG="$(date +%Y-%m-%d)-<short-query-slug>"
OUT_DIR=".asta/auto-exp-designer/$SLUG"
mkdir -p "$OUT_DIR"

asta artifacts --input "$TASK_DIR" --output "$OUT_DIR" --format html
open "$OUT_DIR/index.html"
```

`<short-query-slug>` is a 3–5 word kebab-case version of the question (something like `react-split-vs-combined`).

Then hand off to the **Asta Artifacts** skill so it gets indexed into `asta-documents` and can be searched later. Pass `auto-exp-designer` as the skill and the same slug.

## Step 6 — Tell the user what they got

Show them, in this order:

1. **The report is open**:

   > Opened the experiment design report: `<absolute path to index.html>`

2. **How to find it later**:

   > Indexed N artifacts in `.asta/auto-exp-designer/<slug>/index.yaml`.
   > Search with `asta documents search --summary='<concept>' --root=.asta/auto-exp-designer/<slug>`, or just open the folder: `open <absolute path to slug dir>`

   Use absolute paths. Pick `<concept>` from a term that's central to the design.

3. **A short summary** — 2–4 sentences in your own words about what the design actually proposes. What's the experiment? What's it varying? What's it measuring? Read the design (`experiment_name`, `experiment_description`, `plain_language_description`) and write fresh — don't template.

4. **Table of aspects** — one row per item in `recipe_to_implement[]`: aspect name + a short sentence on what it's for. Add a relevance column if `relevance` is set.

Don't dump JSON. Don't repeat the plain-language description. Don't end with "let me know if you'd like…" — the search/open links already cover that.

## References

- Auto Experiment Designer: <https://github.com/allenai/auto-experiment-designer>
- Asta SDK: <https://github.com/allenai/asta-sdk>
- A2A spec: <https://a2a-protocol.org/latest/specification/>
