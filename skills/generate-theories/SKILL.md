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

Uses the [Theorizer](https://github.com/allenai/asta-theorizer) agent (via
`asta-gateway`) to find papers, extract evidence, write theories, and score
novelty. Auth: `asta auth login`.

The CLI is generated from the agent card — every subcommand, flag, and default.
Discover the surface yourself:

- `asta generate-theories --help` — list subcommands.
- `asta generate-theories card` — full agent card.
- `asta generate-theories describe <skill-id>` — input schema for one skill.

## What this skill is good for

- Generating literature-grounded scientific theories about causal questions
  ("how does X affect Y, via what mechanism, in what domain").
- Finding evidence in published papers to support or contradict a hypothesis.
- Scoring theory novelty against existing literature.
- Surveying what's known and unknown in a research area through extracted
  variables and findings.

## The pipeline

Theorizer's literature-driven theory generation is **three composable stages**:

```
literature-theory-generation
    = find-and-extract → form-theory → evaluate-novelty
```

- **`find-and-extract`** — searches papers for the research question and extracts
  evidence from the papers via an extraction schema. Outputs: paper list + 
  extraction findings. No theories yet.
- **`form-theory`** — takes those findings and writes a set of theories, each
  with supporting and conflicting paper evidence attached.
- **`evaluate-novelty`** — scores each theory statement against the retrieved
  literature.

`literature-theory-generation` is the **bundled end-to-end version** that runs
all three back-to-back without pause. Convenient when the user wants results in
one shot; less useful when the user wants to inspect or steer between stages.

Two more standalone subcommands round out the surface:

- **`resume-extraction`** — add more papers to a prior run and extract from them
  (useful after a partial failure, or to grow the evidence base).
- **`form-theory`** / **`evaluate-novelty`** also accept a prior run's `task_id`,
  so a user can re-theorize or re-evaluate without paying to find papers again.

## Two modes: automatic vs piecemeal

Because the pipeline is composable, the user has a choice: let it run
straight through, or step through stage by stage.

- **Automatic** — single `literature-theory-generation` call. Submit, wait,
  render results. Fastest path; user can't steer mid-run.
- **Piecemeal** — call the three stages separately. After each stage, show the
  user what came out and ask whether to continue, stop, or edit. Slower but
  steerable; user can prune papers, refine the query, or stop after they have
  what they need.

On the user's first generate-theories request in a session, after shaping the
question but before submitting, ask which mode they want. One chat question
with the two options, briefly explain the trade-off.

After they answer, remember the choice for the rest of the session. If they
later signal they want the other mode ("actually, just run it" / "wait, let me
see the papers first"), respect that without re-confirming.

Exception: if the user's original phrasing already commits ("just run it,"
"use defaults," "I'll review papers before extraction"), skip the question
and honor the implied choice.

## Between stages

When running piecemeal, after each stage completes, surface a clear summary
in chat oriented to the decision the user is about to make, then offer three
options:

| Option | What happens |
|---|---|
| **Continue** | Run the next stage on this run's output |
| **Stop** | End here. Render whatever results exist via the Asta Artifacts handoff |
| **Edit** | Modify before continuing (see below) |

The summary should be tight and decision-oriented — not a dump of everything.

**After `find-and-extract`:**
- Show the paper list (titles + 1-line summary of what was extracted from each).
- *Edit* means: the user may want to add or remove specific papers,
  edit the extraction schema used to gather evidence, or restart with a refined query.

**After `form-theory`:**
- Show the theories: name + 2-3 sentence core idea + supporting/contradicting
  paper counts.
- *Edit* means: re-run `form-theory` with a different `generation_objective`
  (accuracy-focused vs novelty-focused) or against a subset of the extractions.

**After `evaluate-novelty`:**
- This is the terminal stage — there is no "continue."
- Show per-theory novelty labels in plain English.
- *Edit* means: re-run novelty against a refined theory subset, or branch into
  `find-literature` to challenge specific claims.

If the user picks **Stop** at any stage, hand off to Asta Artifacts as usual to
export and index whatever was produced. Partial extractions and theories are
valid artifacts.

## Shape the question

This applies **only when the next call generates or forms theories** —
specifically `literature-theory-generation` (full pipeline) or `form-theory`
(standalone or continuation). **Do NOT** shape the query when the next call
triggers `find-and-extract`, `evaluate-novelty`, or `resume-extraction`.

A good Theorizer theory question names five things, and the agent works
dramatically better when they're explicit:

1. **Frame** — phrased as "Build a theory of how..." or "Make theories of
   how...". A phrasing convention the agent expects.
2. **Intervention** — the independent variable being varied (e.g., *source
   citations*, *response latency*, *anthropomorphic phrasing*).
3. **Mediating mechanism** — the hypothesized driver of the effect (e.g.,
   *perceived transparency*, *cognitive load*, *anchoring*).
4. **Outcomes** — concrete dependent variables (e.g., *trust*, *retention*,
   *task completion*).
5. **Scope** — the domain the theory should apply to (e.g., *consumer
   chatbots*, *enterprise search*, *coding agents*).

A vague question that fires through the full pipeline can burn 15–25 minutes
and several dollars producing theories that don't answer what the user actually
meant. Shaping costs ~30 seconds and protects that investment.

**How to handle the user's question — three paths, gated by the intervention:**

The intervention (what's being varied) is the load-bearing piece. The agent
searches literature against it; the mechanism, scope, and outcome are all
downstream of which intervention you commit to. If the user didn't name a
specific intervention, **don't guess** — silently picking one commits the
whole run to an angle the user never chose, and Theorizer will dutifully
narrow further. Inferred interventions consistently produce off-target
theories.

1. **Proceed silently** if all five pieces are clearly named. The frame can
   be added without confirmation — it's just phrasing.

2. **Reshape and confirm** if the user named a specific intervention AND a
   specific scope, but mechanism or outcome is missing or vague. Show
   before/after with a one-line note on what you inferred. *Allowed silent
   inference:* mechanism (from intervention + outcome + scope) and minor
   scope tightening. *Not allowed:* inferring the intervention itself, or
   inventing a scope from nothing.

3. **Ask with candidate angles** if intervention is missing, ambiguous, or
   could plausibly be one of several different things. Present 2–3 concrete,
   fully-formed candidate questions that vary the intervention (and scope,
   if also open) so the user picks rather than fills in blanks.

**Format the reshape (path 2) like this:**

```
**Your question:** How does response latency affect satisfaction in chatbots?

**Reshaped:**
Build a theory of how response latency affects user satisfaction, via
perceived responsiveness, in consumer chatbots.

_I inferred the mechanism (perceived responsiveness) and tightened scope to
consumer chatbots. Approve, edit, or tell me to use your original?_
```

Three valid responses:
- **Approve** → continue to mode selection with the reshaped question.
- **Edit** → take their edits and submit those.
- **Use original** → respect it, but note once that the run may surface less
  relevant theories.

**Format the ask-with-candidates (path 3) like this:**

```
**Your question:** What makes people trust AI?

I can take this in a few different directions — pick one (or sketch your own):

**A.** Build a theory of how *source citations* affect user trust via
*perceived transparency*, in *consumer AI chatbots*.

**B.** Build a theory of how *uncertainty disclosure* (e.g., "I'm not sure")
affects user trust via *calibrated reliance*, in *medical-decision-support AI*.

**C.** Build a theory of how *anthropomorphic phrasing* affects user trust via
*social presence*, in *AI personal assistants*.

Tell me A, B, C, or describe your own angle (intervention + scope) and I'll
shape from there.
```

Make the candidates genuinely different — vary the intervention (not just the
scope), so the user is choosing a research direction, not picking between near
duplicates. If the user picks A/B/C, treat that as approval and proceed.
If they describe their own angle, reshape it (path 2) and confirm.

**Non-research questions** (e.g., "what should I name my startup?", "summarize
this paper") — say plainly that Theorizer is for posing causal theories grounded
in literature, and offer to reframe or hand off to a different skill. Don't
force the rubric onto a question with no theoretical hypothesis.

**Within a session**, don't re-shape on subsequent runs unless the user changes
their question substantively. Repeating the dance is friction.

## How to dispatch

1. **Classify** the user's request:
   - A clear request for theories from a research question → mode selection
     and then either `literature-theory-generation` (automatic) or the
     three-stage pipeline (piecemeal).
   - A request that targets one stage explicitly (e.g., "just find papers,"
     "re-theorize from this prior run," "check novelty on these theories")
     → use the single matching subcommand and skip mode selection.
   - A continuation of a prior run → `resume-extraction`, or `form-theory` /
     `evaluate-novelty` with `task_id` of the prior run.

2. **Capture the research question.** If the user hasn't supplied one, ask
   for it. This is the only universally required input.

3. **Shape the question** — but only when the next call generates theories
   (`literature-theory-generation` or `form-theory`). Skip for:
   - `find-and-extract` standalone — pass the literature topic through.
   - `evaluate-novelty`, `resume-extraction` — no query input needed.

   See *Shape the question* for the rubric and the do-not-shape list.

4. **Resolve mode** (first run only). Skip if the user committed to a mode
   in their phrasing.

5. **Resolve other inputs.** Run `asta generate-theories describe <skill-id>`
   to see required and key optional fields. For any missing required fields
   and the 2–3 most impactful optionals (papers, objective, novelty), ask one
   chat question unless the user said "use defaults."

6. **Surface what's being submitted.** One line:
   *"Using N papers, novelty evaluation on, accuracy-focused. Submitting —
   say 'tune' to change anything."* This is the user-side half of the
   defaults-visibility pattern.

7. **Submit.**
   - Automatic mode: one `asta generate-theories literature-theory-generation`
     call.
   - Piecemeal mode: `asta generate-theories find-and-extract` first, then
     surface results and offer continue/stop/edit, then `form-theory` and
     `evaluate-novelty` in sequence with the same checkpoint pattern.

   Each subcommand takes a single JSON `PAYLOAD` argument. Inline JSON works
   for short payloads; for long queries, write to a file and use
   `@path/to.json`. Object-typed inputs also accept a URI (`file://`, `s3://`,
   `https://`).

   The CLI streams progress to stderr and prints the final Task JSON to stdout
   when the task terminates. The CLI handles polling (5s/15s/60s backoff) —
   don't write your own loop. Use `--no-wait` only if the user explicitly asked
   for fire-and-forget. In an interactive session, run the submit with
   `Bash(..., run_in_background=true)` and wait for the completion notification.

## Defaults

Schema defaults. The runtime "Using: ..." line in dispatch step 6 surfaces
whatever was actually resolved so the user can intervene before submission.

| Setting | Default | Effect | Tune when |
|---|---|---|---|
| `max_papers_to_retrieve` | 10 | ~3–8 min runtime | Bump to 30 for medium runs, 100 for full coverage (15–25 min) |
| `generation_objective` | `accuracy-focused` | Favors well-supported theories | Set `novelty-focused` if user emphasizes novelty or new theories |
| `do_qualified_novelty_evaluation` | `true` | Adds 30–60 min and ~$5–10 | Skip for fast iteration. No effect in piecemeal mode (the evaluate-novelty stage runs separately) |

## After the task completes

Hand off to the **Asta Artifacts** skill (`asta-preview:artifacts`) to export
and index the result — it owns the path convention, manifest, and
asta-documents registration. Pass `generate-theories` as the invoking skill
and a slug shaped `YYYY-MM-DD-<short-query-slug>` derived from the theory
query.

In piecemeal mode, export after each stage the user stops or completes at —
don't wait for the full pipeline to finish.

Then write, in chat, in this order:

1. **Where it lives** — the indexed path + the `asta documents search` command
   + `open <absolute path>`. Use absolute paths.
2. **One-paragraph synthesis** — 2–4 fresh sentences. What do the theories
   collectively argue? Where do they converge / diverge? What's the headline
   "so what"? Read the theories; don't template.
3. **Table of theories** — one row per theory: name + 2–3 sentence core idea.
   Add a *novelty* column if novelty was scored.

No "let me know if you'd like…" tail — the search/open links cover it.

## Resumption / errors

- `state=input-required` → CLI prints a `Continue with: …` hint. Relay to the
  user; resend with `asta generate-theories send-message --task-id <id>
  --context-id <ctx> '<reply>'` and re-run the wait.
- `state=failed` → report `status.message` and stop.
- Network/protocol errors exit non-zero with a JSON `{error: …}` on stderr.
- Partial pipeline (piecemeal) → the user can always continue later by passing
  the prior run's `task_id` to `form-theory` or `evaluate-novelty`.

## References

- Theorizer: <https://github.com/allenai/asta-theorizer>
- Agent card / schemas: `asta generate-theories card` /
  `asta generate-theories describe <skill-id>`
- A2A spec: <https://a2a-protocol.org/latest/specification/>

<!-- - Shared patterns:
  - `shared-patterns/defaults-visibility.md`
  - `shared-patterns/question-shaping.md`
  - `shared-patterns/mode-selection.md`
  - `shared-patterns/stage-checkpoints.md` -->