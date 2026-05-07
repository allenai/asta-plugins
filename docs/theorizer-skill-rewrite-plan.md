# Plan — rewrite the Generate Theories skill on top of the new typed CLI

**Status:** design, awaiting implementation
**Touches:** `asta-plugins` only (the underlying CLI changes shipped on the
`cli-from-card` branch in asta-sdk, commit `4fbced2`)
**Owner:** Charlie M.
**Companion plan:** `asta-sdk/docs/cli-from-card-plan.md` (the CLI side)

---

## 1. Goal

`skills/generate-theories/SKILL.md` today is 140 lines: a hand-curated
7-step workflow with a hand-rolled JSON payload (4 of 14 schema fields
exposed), a hand-rolled bash polling loop, a hand-rolled "novelty
shortcut" heuristic, and per-flow templating. Almost all of it is now
redundant: the new `make_a2a_group` CLI emits typed flags per skill,
polls and streams progress itself, and exposes `card` + `describe`
introspection for free.

The rewrite collapses that into a **medium-length skill (~60 lines)**
that:

- Lists the 5 user-visible flows in one table, each pointing at a
  generated CLI subcommand.
- Tells the model to dispatch via classification + `AskUserQuestion`
  (with chat fallback) when the request is ambiguous.
- Uses `asta theorizer describe <skill-id>` to discover required + key
  optional inputs, and asks one chat question for missing values
  (unless the user said "use defaults").
- Hands off to the **Asta Artifacts** skill for export + indexing
  (path convention, manifest, asta-documents registration all live there).
- Keeps the human-facing summary instructions (one-paragraph synthesis,
  table of theories, no AI-slop tail).

Net result: the skill stops being a re-implementation of the agent's
contract and becomes a thin dispatcher over the CLI.

---

## 2. The five flows

| #  | User says…                                                                          | Skill                              | CLI                                                                                          |
|----|-------------------------------------------------------------------------------------|------------------------------------|----------------------------------------------------------------------------------------------|
| 1  | "Generate theories about X" (the default request)                                    | `literature-theory-generation`    | `asta theorizer literature-theory-generation --theory-query "X" [defaults]`                  |
| 2  | "Use these papers I already have" (BYO PDF / paper store)                            | `literature-theory-generation`    | `… --paper-store @./papers.json` (or `s3://…` / `file://…`)                                  |
| 3  | "Just extract the evidence, don't theorize yet"                                      | `find-and-extract`                 | `asta theorizer find-and-extract --theory-query "X"`                                         |
| 4  | "Re-run theory generation on these extraction results, novelty-focused this time"    | `form-theory`                      | `asta theorizer form-theory --paper-store @./extraction.json --generation-objective novelty-focused` |
| 5  | "Score novelty on these existing theories"                                           | `evaluate-novelty`                 | `asta theorizer evaluate-novelty --theory-ids …`                                             |
| 6  | "Resume the failed extraction from run 7c4a-…"                                      | `resume-extraction`                | `asta theorizer resume-extraction --previous-run-id 7c4a-…`                                  |

> **Verified:** `asta-theorizer-internal/src/asta/server.py` registers
> all 5 tasks via `@asta.task(...)` decorators at lines 49, 106, 154,
> 205, 250. So all 5 flows above are live against a running theorizer
> instance — no aspirational paths.

---

## 3. The rewritten SKILL.md (proposed)

Length target: ~60 lines (vs 140 today). No flag tables — the CLI's
`--help` and `describe` cover those. No bash polling — the CLI handles
sync wait. No JSON construction — typed flags handle that.

```markdown
---
name: Generate Theories
description: This skill should be used when the user asks to "generate theories", "theorize about", "what theories explain", "form scientific theories", "literature-driven theories", "hypothesize", "form hypotheses", "generate hypotheses", "what hypotheses explain", "run the theorizer", or wants AI-generated, literature-grounded scientific theories or hypotheses about a research question.
metadata:
  internal: true
allowed-tools:
  - Bash(asta auth login)
  - Bash(asta auth status)
  - Bash(asta theorizer *)
  - Bash(asta artifacts *)
  - Bash(asta documents *)
  - Bash(open *)
---

# Generate Theories

Uses the [Theorizer](https://github.com/allenai/asta-theorizer) agent
(via `asta-gateway`) to find papers, extract evidence, write theories,
and score novelty. Auth: `asta auth login`.

The CLI is generated from the agent card — every skill, flag, and
default. Run `asta theorizer --help` to see all subcommands, and
`asta theorizer describe <skill-id>` for a specific skill's input
schema. `asta theorizer card` prints the full card.

## Flows

| User wants                                          | Run                                |
|-----------------------------------------------------|------------------------------------|
| End-to-end theory generation from a question        | `literature-theory-generation`     |
| End-to-end with their own pre-collected papers      | `literature-theory-generation` + `--paper-store @file.json` |
| Just find + extract evidence (no theories yet)      | `find-and-extract`                 |
| Theorize from existing extraction results           | `form-theory`                      |
| Score novelty on existing theories                  | `evaluate-novelty`                 |
| Resume a failed/partial extraction run              | `resume-extraction`                |

## How to dispatch

1. **Classify** the user's request into one of the 6 rows above.
2. If unclear, fire one `AskUserQuestion` with the rows as options.
   If `AskUserQuestion` isn't available, list them in chat and wait.
3. Run `asta theorizer describe <skill-id>` to see required + key
   optional fields.
4. Identify which required fields the user already supplied. For any
   missing required fields and the 2–3 most impactful optionals
   (papers, objective, novelty), **ask one chat question** unless the
   user said "use defaults" — then submit immediately.
5. Submit. The CLI streams progress on stderr and prints the final
   Task JSON on stdout when the task terminates. Use `--no-wait` only
   if the user asked for fire-and-forget.

## Defaults worth knowing

These are the schema defaults — you don't need to repeat them unless
the user wants to tune one:

- `max_papers_to_retrieve`: 10 (~3–8 min). Bump to 30 for medium runs,
  100 for full coverage (15–25 min).
- `generation_objective`: `accuracy-focused`. If the user emphasizes
  *novelty* or *new theories*, set `novelty-focused` without asking.
- `do_qualified_novelty_evaluation`: `true`. Adds 30–60 min and ~$5–10.
  Skip only if the user wants fast iteration.

## After the task completes

Hand off to the **Asta Artifacts** skill to export and index the result
(it owns the path convention, manifest, and asta-documents
registration). Pass `generate-theories` as the invoking skill and a
`YYYY-MM-DD-<short-slug>` slug derived from the theory query.

Then write, in chat, in this order:

1. **Where it lives** — the indexed path + the `asta documents search`
   command + `open <absolute path>`. Use absolute paths.
2. **One-paragraph synthesis** — 2–4 fresh sentences. What do the
   theories collectively argue? Where do they converge / diverge?
   What's the headline "so what"?
3. **Table of theories** — one row per theory: name + 2–3 sentence
   core idea. Add a *novelty* column if novelty was scored.

No "let me know if you'd like…" tail — the search/open links cover it.

## Resumption / errors

- `state=input-required` → CLI prints a `Continue with: …` hint.
  Relay to the user; resend with `asta theorizer send-message --task-id
  <id> --context-id <ctx> '<reply>'` and re-run the wait.
- `state=failed` → report `status.message` and stop.
- Network/protocol errors exit non-zero with a JSON `{error: …}` on
  stderr.

## References

- Theorizer: <https://github.com/allenai/asta-theorizer>
- Agent card / schemas: `asta theorizer card` / `asta theorizer describe`
- A2A spec: <https://a2a-protocol.org/latest/specification/>
```

### What I removed and why

| Removed                                            | Why                                                                                                  |
|----------------------------------------------------|------------------------------------------------------------------------------------------------------|
| Hand-rolled JSON payload in Step 4                  | New CLI takes typed flags from the schema.                                                          |
| Hand-rolled bash polling loop in Step 5             | New CLI polls itself with 5/15/60s backoff and streams to stderr.                                   |
| Hand-curated parameter list (4 of 14 fields)        | `asta theorizer describe <skill-id>` shows the live, complete schema.                               |
| 7-step process with confirmation/interview branches | One classification step + one chat question for missing values. Trust the user's wording.            |
| Per-flow templating in chat                         | The flow table + dispatcher absorb this.                                                             |
| Export bash recipe                                  | Asta Artifacts skill already owns it (`skills/artifacts/SKILL.md` lines 19–28, 37–58).               |
| asta-documents indexing recipe                      | Same — Asta Artifacts owns it (lines 59–70).                                                         |

### What I kept and why

| Kept                                                | Why                                                                                                  |
|----------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `AskUserQuestion`-when-available pattern            | Confirmed: same UX as the existing skill, fallback for headless harnesses.                          |
| Novelty shortcut ("user emphasizes novelty → set novelty-focused without asking") | Valuable heuristic that's worth a single line in the defaults section. |
| Summary instructions (synthesis + table)            | Asta Artifacts skill exports + indexes; it does *not* synthesize the human-facing summary.          |
| Resumption guidance                                 | The CLI prints a hint, but the skill body should remind the model how to use it.                    |
| Allowed-tools frontmatter                           | Same shape as today; only the `asta theorizer *` glob replaces `asta generate-theories *`.          |

### Naming

Plugin command currently: `asta generate-theories`. New CLI surface
will register as `asta theorizer` (matches the agent card name). Two
options:

1. **Keep `asta generate-theories`** — rename in `asta-plugins/src/asta/theorizer.py` from `name="generate-theories"` to `name="generate-theories"` (no change), so the SKILL.md continues to use `asta generate-theories <skill-id>`.
2. **Rename to `asta theorizer`** — rename in the plugin to `name="theorizer"`. SKILL.md uses `asta theorizer <skill-id>`. Cleaner mapping to the agent card; small breakage for any scripts calling `asta generate-theories send-message …` directly.

**Recommendation:** keep `asta generate-theories` for compat. The
SKILL.md draft above uses `asta theorizer` for readability — if we
keep the legacy name, s/`asta theorizer`/`asta generate-theories`/g.
Decision belongs to the PR review.

---

## 4. What changes in the repo

| Path                                                   | Change                                                                       |
|--------------------------------------------------------|------------------------------------------------------------------------------|
| `skills/generate-theories/SKILL.md`                    | Rewrite (~140 → ~60 lines). New text per §3.                                 |
| `plugins/asta-preview/skills/generate-theories/SKILL.md` | Regenerated by `make build-plugins`. Don't edit by hand.                   |
| `pyproject.toml`                                       | Bump `asta-agent[a2a-client]>=1.0.9`. Re-lock.                               |
| `tests/test_skills_generate_theories.py` (new)         | Static lint of the rewritten SKILL.md (frontmatter, allowed-tools globs).    |
| `tests/integration/test_theorizer_skill_live.py` (new) | Headless `claude -p` driver against the real theorizer (see §5).             |
| `Makefile`                                             | `make test-skill-live` target wraps the live driver.                         |

No changes needed in `src/asta/theorizer.py` (the `make_a2a_group`
caller). The new asta-agent already drives skill subcommand
generation from the card.

---

## 5. Closed-loop testing — headless `claude -p` against the real theorizer

> **Why a real theorizer, not the fake one used in asta-sdk E2E?**
> The user wants to verify the skill produces *useful* output (good
> theories, sensible summaries) — not just that the right CLI command
> fired. The fake theorizer can't produce real theories. So this test
> lives at the asta-plugins layer and uses the real theorizer end to
> end. It's slow ($) and gated behind `ASTA_LIVE_SKILL_TEST=1`.

### 5.1 Spawning the real theorizer

```bash
# tests/integration/spawn_theorizer.sh
#!/usr/bin/env bash
set -euo pipefail
cd "${ASTA_THEORIZER_INTERNAL:-$HOME/workspace/asta-theorizer-internal}"
set -a; source "${LILY_ENV:-$HOME/workspace/lily/.env}"; set +a
export API_KEY="${THEORIZER_TEST_API_KEY:-skill-live-test-key}"
export THEORIZER_PORT="${THEORIZER_TEST_PORT:-9077}"
exec .venv/bin/python -m uvicorn asta.server:app \
    --host 127.0.0.1 --port "$THEORIZER_PORT"
```

The harness waits for `/healthz` to return 200, then injects the
`THEORIZER_TEST_API_KEY` into the environment that `claude -p` runs
in (`ASTA_A2A_API_KEY=$THEORIZER_TEST_API_KEY`). It also overrides
the URL the plugin's `make_a2a_group` resolves: `ASTA_GATEWAY_URL=
http://127.0.0.1:$THEORIZER_TEST_PORT/__BARE__`. We add a small
"bare" override mode in `src/asta/theorizer.py` so the URL factory
can return the raw URL when `ASTA_THEORIZER_URL` is set, bypassing
the `/api/theorizer` gateway prefix.

### 5.2 The driver

```python
# tests/integration/test_theorizer_skill_live.py

import json, os, subprocess, time, uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
PLUGIN_DIR = ROOT / "plugins" / "asta-preview"


@pytest.fixture(scope="session")
def theorizer():
    """Spawn the real theorizer; tear down at session end."""
    if "ASTA_LIVE_SKILL_TEST" not in os.environ:
        pytest.skip("set ASTA_LIVE_SKILL_TEST=1 to run live skill tests")
    proc = subprocess.Popen(["bash", str(ROOT / "tests/integration/spawn_theorizer.sh")])
    try:
        _wait_healthy("http://127.0.0.1:9077", 60)
        yield "http://127.0.0.1:9077"
    finally:
        proc.terminate(); proc.wait(timeout=10)


def _claude(prompt: str, theorizer_url: str, log_path: Path) -> dict:
    """Run claude -p against the asta-preview plugin; capture transcript."""
    cp = subprocess.run(
        ["claude",
         "-p", prompt,
         "--plugin-dir", str(PLUGIN_DIR),
         "--allowed-tools", "Bash(asta *)",
         "--output-format", "stream-json"],
        env={
            **os.environ,
            "ASTA_THEORIZER_URL": theorizer_url,
            "ASTA_A2A_API_KEY": "skill-live-test-key",
        },
        capture_output=True, text=True, timeout=3600,
    )
    log_path.write_text(cp.stdout)
    return cp


def _tool_calls(transcript: str, kind="bash") -> list[dict]:
    """Extract tool invocations from the stream-json transcript."""
    calls = []
    for line in transcript.splitlines():
        try: ev = json.loads(line)
        except json.JSONDecodeError: continue
        if ev.get("type") == "assistant":
            for blk in ev.get("message", {}).get("content", []):
                if blk.get("type") == "tool_use" and blk.get("name", "").lower() == kind.lower():
                    calls.append(blk)
    return calls
```

### 5.3 The five canonical scenarios

Each test runs one prompt, asserts on the tool calls, then on the
final Task JSON, then on the final assistant message ("is the summary
actually useful?"). All five run in parallel — `pytest-xdist`
recommended.

| # | Prompt                                                                              | Expected tool call                                                                     | Output assertion                                  |
|---|-------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|---------------------------------------------------|
| A | `Generate theories about why language models hallucinate.`                          | `asta … literature-theory-generation --theory-query …` (one)                            | Final state=completed; ≥1 theory artifact; assistant summary mentions "theories" + "hallucination" |
| B | `I have papers in /tmp/papers.json — generate theories from those.` (write a small fixture first) | `asta … literature-theory-generation … --paper-store @/tmp/papers.json`            | Same; agent received the file content                |
| C | `Just find and extract evidence for "scaling laws", don't theorize yet.`            | `asta … find-and-extract --theory-query …`                                              | Final state=completed; extraction artifact present  |
| D | `Re-run theory generation on these extraction results: /tmp/extraction.json — focus on novelty.` | `asta … form-theory --paper-store @/tmp/extraction.json --generation-objective novelty-focused` | Same                                  |
| E | `Score novelty on the theories from run <prev-task-id>.`                            | `asta … evaluate-novelty …`                                                             | Per-statement novelty assessment in artifacts        |

For scenarios A–E that require a prior run (B's papers, D's extractions,
E's prior task), the harness primes those by running the dependency
scenario first and feeding its output into the next test as a fixture.

### 5.4 What "actually look at the output" means

For each scenario the harness asserts:

1. **Tool dispatch correct.** The expected `asta theorizer <skill-id>`
   call appears in the transcript exactly once, with the expected
   flags (verified via regex on the bash invocation string).
2. **No anti-patterns.** The transcript does NOT contain any of:
   `asta generate-theories send-message '{` (the old hand-rolled JSON
   path), or `sleep 60` in a bash loop (the old polling pattern), or
   raw `curl` calls to the agent.
3. **Final task succeeded.** The captured Task JSON has
   `status.state == "completed"` and at least one artifact.
4. **Summary is useful.** The final assistant message must contain:
   - The path under `.asta/generate-theories/` (proves Artifacts skill
     handed off correctly);
   - At least one of: "theory" or "theories" or "hypothesis" or "law"
     (proves it's talking about the actual output);
   - A markdown table with ≥2 rows (proves the per-theory table is
     present);
   - No "let me know if you'd like" / "I hope this helps" kind of
     trailing AI-slop (regex blocklist).
5. **Transcript is dumped to disk** at
   `tests/integration/transcripts/<scenario>-<timestamp>.json` so a
   human can quickly eyeball any failure.

### 5.5 Cost & wall-clock

- Each scenario: ~$1–10 in LLM credits (Theorizer + Claude Code), +5–60
  minutes wall-clock depending on novelty assessment.
- Full live suite: ~$5–50, ~30–90 minutes.
- Default: skipped (`pytest.skip` unless `ASTA_LIVE_SKILL_TEST=1`).
- Recommended cadence: nightly on a low-cost subset (scenario A only),
  full sweep before release.

### 5.6 What the static layer covers (every PR)

To catch the cheap regressions without the live cost:

```python
# tests/test_skills_generate_theories.py

import pathlib, re, yaml

SKILL = pathlib.Path("skills/generate-theories/SKILL.md")

def test_frontmatter_valid():
    body = SKILL.read_text()
    fm = yaml.safe_load(body.split("---")[1])
    assert fm["name"] == "Generate Theories"
    assert "asta theorizer *" in " ".join(fm["allowed-tools"])

def test_no_old_command_strings():
    body = SKILL.read_text().lower()
    # The old hand-rolled patterns must be gone.
    assert "sleep 60" not in body
    assert 'asta generate-theories send-message' not in body
    assert "max_papers_to_retrieve" not in body  # was hardcoded; now via flag

def test_skill_under_target_length():
    lines = [l for l in SKILL.read_text().splitlines() if l.strip()]
    assert len(lines) <= 80, f"skill is {len(lines)} non-empty lines"

def test_references_describe_and_card():
    body = SKILL.read_text()
    assert "asta theorizer describe" in body
    assert "asta theorizer card" in body

def test_lists_all_six_flow_rows():
    body = SKILL.read_text()
    for sk in ("literature-theory-generation", "find-and-extract",
               "form-theory", "evaluate-novelty", "resume-extraction"):
        assert sk in body
```

---

## 6. Test matrix summary

| Layer              | File                                          | Cost / latency     | When run                                       |
|--------------------|-----------------------------------------------|--------------------|-----------------------------------------------|
| Static lint        | `tests/test_skills_generate_theories.py`      | <1s, free          | Every PR                                       |
| CLI E2E (asta-sdk) | `asta-sdk/.../tests/e2e/test_e2e.py` (40 tests) | ~9s, free        | Every PR (asta-sdk)                            |
| Live skill         | `tests/integration/test_theorizer_skill_live.py` | $1–50, 5–90 min  | Opt-in via `ASTA_LIVE_SKILL_TEST=1`            |

---

## 7. Rollout

1. **Land the asta-sdk PR** (`cli-from-card`, commit `4fbced2`) so the
   new CLI ships in `asta-agent==1.0.9`.
2. **Bump** `asta-agent[a2a-client]>=1.0.9` in `asta-plugins/pyproject.toml`.
3. **Rewrite** `skills/generate-theories/SKILL.md` per §3.
4. **Add** the static + live test files per §5.
5. **Regenerate** plugin packages: `make build-plugins`.
6. **Run** the live tests once locally against the real theorizer to
   confirm the assistant's summaries are usable.
7. **CI** runs the static layer on every PR; live tests are nightly
   or on-demand.
8. **Apply the same pattern** to `auto-exp-designer` (similar
   structure, single-skill agent currently) and `analyze-data` (has
   the bespoke `upload` subcommand, but otherwise the dispatcher
   pattern applies).

---

## 8. Open questions

1. **Plugin name: `asta theorizer` vs `asta generate-theories`.**
   Plan keeps the legacy name. Revisit if the new CLI noise makes the
   inconsistency painful.
2. **Whether to inline `!` `` dynamic context injection.** The
   official docs say it works in SKILL.md and runs at skill load, but
   it adds a synchronous `asta theorizer --help` to every invocation.
   Probably worth the latency only if drift becomes a problem; deferred.
3. **`ASTA_THEORIZER_URL` override hook.** The plugin's `_theorizer_url`
   reads `ASTA_GATEWAY_URL` and appends `/api/theorizer`. For local
   testing we want to point straight at the spawned theorizer.
   Adding a `ASTA_THEORIZER_URL` short-circuit in
   `asta-plugins/src/asta/theorizer.py` is one tiny change; flagged
   here so it doesn't surprise reviewers.
4. **Does the live test driver need to seed Claude Code config?**
   `claude -p` may inherit the user's defaults (model, context
   limits). The harness should pin `--model` and a clean
   `CLAUDE_CONFIG_DIR=$(mktemp -d)` so test results are repeatable.
   Confirm during implementation.
