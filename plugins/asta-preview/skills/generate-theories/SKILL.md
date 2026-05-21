---
name: generate-theories
description: This skill should be used when the user asks to "generate theories", "theorize about", "what theories explain", "form scientific theories", "literature-driven theories", "hypothesize", "form hypotheses", "generate hypotheses", "what hypotheses explain", "run the theorizer", or wants AI-generated, literature-grounded scientific theories or hypotheses about a research question.
metadata:
  internal: true
allowed-tools: Bash(asta auth login) Bash(asta auth status) Bash(asta generate-theories *) Bash(asta artifacts *) Bash(asta documents *) Bash(open *)
---

# Generate Theories

Uses the [Theorizer](https://github.com/allenai/asta-theorizer-internal) agent (via `asta-gateway`) to find papers, extract evidence, write theories, and score novelty. Auth: `asta auth login`.

The CLI is generated from the agent card — every subcommand, flag, and default. Discover the surface yourself:
- `asta generate-theories --help` — list subcommands.
- `asta generate-theories card` — full agent card.
- `asta generate-theories describe <skill-id>` — input schema for one skill.

This skill is in two halves. The **first** describes what Theorizer is — its three composable stages, the bundled end-to-end version, and the standalone subcommands. The **second** describes how to handle a generate-theories request end-to-end — choosing a mode, shaping the question, dispatching, checkpoints, handoff, and error handling.

**Voice and tone:** Follow [`shared-patterns/voice-and-tone.md`](../../shared-patterns/voice-and-tone.md) for all user-facing chat. Applies to every output the user reads.

## What this skill is good for

- Generating literature-grounded scientific theories about causal questions ("how does X affect Y, via what mechanism, in what domain").
- Finding evidence in published papers to support or contradict a hypothesis.
- Scoring theory novelty against existing literature.
- Surveying what's known and unknown in a research area through extracted variables and findings.

## The pipeline

Theorizer's literature-driven theory generation is **three composable stages**:

```
literature-theory-generation = find-and-extract → form-theory → evaluate-novelty
```

- **`find-and-extract`** — searches papers for the research question and pulls theory-relevant findings (entities, variables, results) from each into a structured table via an extraction schema. Outputs: paper list + extraction findings. No theories yet.
- **`form-theory`** — writes a small set of theories from extraction results. Each theory is a few short laws (e.g. *"X causes Y"*) with supporting and conflicting paper evidence attached. Accepts either a prior run's `task_id` or user-supplied extraction results.
- **`evaluate-novelty`** — scores each theory's statements against the retrieved literature, marking each claim as already established, derivable from known work, or genuinely new. Accepts either a prior run's `task_id` or user-supplied theories.

`literature-theory-generation` is the **bundled end-to-end version** that runs all three back-to-back without pause. Convenient when the user wants results in one shot; less useful when the user wants to inspect or steer between stages.

Two more standalone subcommands round out the surface:

- **`build-extraction-schema`** — normalizes the research question, drafts a paper search query, and generates the extraction schema that `find-and-extract` uses. Useful when the user wants to inspect or curate the schema before running the pipeline; pass the produced schema via the `extraction_schema` parameter on `find-and-extract` or `literature-theory-generation`.
- **`resume-extraction`** — add more papers to a prior run and extract findings from them. Useful after failed paper downloads, or to grow the evidence base of a prior run without starting over.

---

## How to run it

The sections below describe the choreography for handling a generate-theories request — what to ask, what to surface, and when.

## Two modes: automatic vs piecemeal

Because the pipeline is composable, the user has a choice: let it run straight through, or step through stage by stage.

- **Automatic** — single `literature-theory-generation` call. Submit, wait, render results. Fastest path; user can't steer mid-run.
- **Piecemeal** — call the three stages separately. After each stage, show the user what came out and ask whether to continue, stop, or edit. Slower but steerable; user can prune papers, refine the query, or stop after they have what they need.

On the user's first generate-theories request in a session, after shaping the question but before submitting, ask which mode they want via `AskUserQuestion` with the two options as choices. Briefly explain the trade-off in each option's description.

After they answer, remember the choice for the rest of the session. If they later signal they want the other mode ("actually, just run it" / "wait, let me see the papers first"), respect that without re-confirming.

Exception: if the user's original phrasing already commits ("just run it," "use defaults," "I'll review papers before extraction"), skip the question and honor the implied choice.

## Between stages

When running piecemeal, after each stage completes, surface a clear summary in chat oriented to the decision the user is about to make, then offer three options:

| Option | What happens |
|---|---|
| **Continue** | Run the next stage on this run's output |
| **Stop** | End here. Render whatever results exist via the Asta Artifacts handoff |
| **Edit** | Modify before continuing (see below) |

The summary should be tight and decision-oriented — not a dump of everything.

### After `find-and-extract`:
- Show the paper list (titles + 1-line summary of what was extracted from each).
- *Edit* means: the user may want to add or remove specific papers, edit the extraction schema used to gather evidence, or restart with a refined query.

### After `form-theory`:
- Show the theories: name + 2-3 sentence core idea + supporting/contradicting paper counts.
- *Edit* means: re-run `form-theory` with a different `generation_objective` (accuracy-focused vs novelty-focused) or against a subset of the extractions.

### After `evaluate-novelty`:
- This is the terminal stage — there is no "continue."
- Show per-theory novelty labels in plain English.
- *Edit* means: re-run novelty against a refined theory subset, or branch into `find-literature` to challenge specific claims.

If the user picks **Stop** at any stage, hand off to Asta Artifacts as usual to export and index whatever was produced. Partial extractions and theories are valid artifacts.

## Shape the question

This applies **only when the next call generates or forms theories** — specifically `literature-theory-generation` (full pipeline) or `form-theory` (standalone or continuation). **Do NOT** shape the query when the next call triggers `find-and-extract`, `evaluate-novelty`, or `resume-extraction`.

A good Theorizer theory question covers four dimensions, and the agent works dramatically better when they're explicit:

1. **Intervention** — the independent variable being varied (e.g., *source citations*, *response latency*, *anthropomorphic phrasing*).
2. **Outcomes** — concrete dependent variables (e.g., *trust*, *retention*, *task completion*).
3. **Mediating mechanism** *(optional)* — the hypothesized driver of the effect (e.g., *perceived transparency*, *cognitive load*, *anchoring*). Theorizer can run without one; include it only when the user supplies it.
4. **Scope** — the domain the theory should apply to (e.g., *consumer chatbots*, *enterprise search*, *coding agents*).

Three well-formed examples (the second one includes an optional mechanism):

- Build a theory of how *spaced retrieval practice* affects *long-term retention* in *undergraduate STEM courses*.
- Build a theory of how *intermittent fasting* affects *insulin sensitivity*, via *autophagy upregulation*, in *adults with metabolic syndrome*.
- Build a theory of how *prescribed burns* affect *grassland biodiversity* in *temperate North American prairies*.

A vague question that fires through the full pipeline can burn 15–25 minutes and several dollars producing theories that don't answer what the user actually meant. Shaping costs ~30 seconds and protects that investment.

**Within a session**, don't re-shape on subsequent runs unless the user changes their question substantively. Repeating the dance is friction.

### How to handle the user's question — audit, then route:

**Don't guess** the required dimensions (Intervention, Outcome, Scope) on the user's behalf. Silently picking one commits the whole run to an angle the user never chose, and Theorizer will dutifully narrow further. Inferred dimensions consistently produce off-target theories.

**Audit first:** Determine whether the user's question contains the three required dimensions (Intervention, Outcome, Scope). Each is either present, missing, or ambiguous. Note whether a mechanism is also present, but its absence is not a gap.

**Then route:**

1. **Proceed silently** if all three required dimensions are present. Don't announce the audit result, don't tell the user the question is "well-formed," don't name the dimensions — move directly to the next dispatch step. Add the "Build a theory of how..." framing yourself.
2. **Poll for what's missing** if any required dimension is missing or ambiguous. In a single message, ask the user about every required gap. Remember that the user does not know about the dimensions. Then reformulate the query as a "Build a theory of how..." statement using their answers and show it for confirmation before submitting.

   **Escape hatch:** End the poll with a one-line note that the user can say *"skip that,"* *"use what I gave you,"* or *"let Theorizer figure it out"* to skip shaping and submit the question as given. Some advanced users prefer under-specifying deliberately. Respect that signal. The user can also opt out in their original message (before any poll happens); if so, skip the poll entirely and submit as given.

3. **Refuse** if the question isn't a causal hypothesis testable against scientific literature (e.g., "what should I name my startup," "summarize this paper"). State plainly that Theorizer's domain is causal scientific theories grounded in published evidence, and offer to reframe the question into that form or hand off to another skill.

#### Route 2 (Poll for what's missing):

```
**Your question:** What makes people trust AI?

I need a few details to shape this into a good theory question:

- **Intervention** — what variable do you want to vary? (e.g., source citations, response latency, anthropomorphic phrasing)
- **Scope** — what domain should the theory apply to? (e.g., consumer chatbots, medical AI, search assistants)

Or I can send your query verbatim, and Theorizer will work with what you've given me. It can often infer the rest from the literature.
```

After they answer, reformulate and confirm:

```
**Reshaped:**
Build a theory of how source citations affect user trust in consumer AI chatbots.

_Approve, edit, or revise?_
```

#### Route 3 (Refuse):

```
**Your question:** What should I name my startup?

Theorizer generates causal scientific theories grounded in the published literature — questions of the form "how does X affect Y, via what mechanism, in what population." Naming a startup isn't a testable causal hypothesis I can ground in papers.
```

## How to dispatch

1. **Classify** the user's request:
   - A clear request for theories from a research question → mode selection and then either `literature-theory-generation` (automatic) or the three-stage pipeline (piecemeal).
   - A request that targets one stage explicitly (e.g., "just find papers," "re-theorize from this prior run," "check novelty on these theories") → use the single matching subcommand and skip mode selection.
   - A continuation of a prior run → `resume-extraction`, or `form-theory` / `evaluate-novelty` with `task_id` of the prior run.

2. **Capture the research question.** If the user hasn't supplied one, ask for it. This is the only universally required input.

3. **Shape the question** — but only when the next call generates theories (`literature-theory-generation` or `form-theory`). Skip for:
   - `find-and-extract` standalone — pass the literature topic through.
   - `evaluate-novelty`, `resume-extraction` — no query input needed.

   See *Shape the question* for the rubric and the do-not-shape list.

4. **Resolve mode** (first run only). Skip if the user committed to a mode in their phrasing.

5. **Resolve other inputs.** Run `asta generate-theories describe <skill-id>` to see required and key optional fields. For any missing required fields and the 2–3 most impactful optionals (papers, objective, novelty), ask one `AskUserQuestion` question unless the user said "use defaults."

6. **Surface what's being submitted.** One line: *"Using N papers, novelty evaluation on, accuracy-focused. Submitting — say 'tune' to change anything."* This is the user-side half of the defaults-visibility pattern.

7. **Submit.**
   - Automatic mode: one `asta generate-theories literature-theory-generation` call.
   - Piecemeal mode: `asta generate-theories find-and-extract` first, then surface results and offer continue/stop/edit, then `form-theory` and `evaluate-novelty` in sequence with the same checkpoint pattern.

   Each subcommand takes a single JSON `PAYLOAD` argument. Inline JSON works for short payloads; for long queries, write to a file and use `@path/to.json`. Object-typed inputs also accept a URI (`file://`, `s3://`, `https://`).

   The CLI streams progress to stderr and prints the final Task JSON to stdout when the task terminates. The CLI handles polling (5s/15s/60s backoff) — don't write your own loop. Use `--no-wait` only if the user explicitly asked for fire-and-forget. In an interactive session, run the submit with `Bash(..., run_in_background=true)` and wait for the completion notification.

## Defaults

Schema defaults. The runtime "Using: ..." line in dispatch step 6 surfaces whatever was actually resolved so the user can intervene before submission.

| Setting | Default | Effect | Tune when |
|---|---|---|---|
| `max_papers_to_retrieve` | 10 | ~3–8 min runtime | Bump to 30 for medium runs, 100 for full coverage (15–25 min) |
| `generation_objective` | `accuracy-focused` | Favors well-supported theories | Set `novelty-focused` if user emphasizes novelty or new theories |
| `do_qualified_novelty_evaluation` | `true` | Adds 30–60 min and ~$5–10 | Skip for fast iteration. No effect in piecemeal mode (the evaluate-novelty stage runs separately) |

## After the task completes

Hand off to the **Asta Artifacts** skill (`asta-preview:artifacts`) to export and index the result — it owns the path convention, manifest, and asta-documents registration. Pass `generate-theories` as the invoking skill and a slug shaped `YYYY-MM-DD-<short-query-slug>` derived from the theory query.

In piecemeal mode, export after each stage the user stops or completes at — don't wait for the full pipeline to finish.

Then write, in chat, in this order:

1. **Where it lives** — the indexed path + the `asta documents search` command + `open <absolute path>`. Use absolute paths.
2. **One-paragraph synthesis** — 2–4 fresh sentences. What do the theories collectively argue? Where do they converge / diverge? What's the headline "so what"? Read the theories; don't template.
3. **Table of theories** — one row per theory: name + 2–3 sentence core idea. Add a *novelty* column if novelty was scored.

No "let me know if you'd like…" tail — the search/open links cover it.

## Resumption / errors

- `state=input-required` → CLI prints a `Continue with: …` hint. Relay to the user; resend with `asta generate-theories send-message --task-id <id> --context-id <ctx> '<reply>'` and re-run the wait.
- `state=failed` → report `status.message` and stop.
- Network/protocol errors exit non-zero with a JSON `{error: …}` on stderr.
- Partial pipeline (piecemeal) → the user can always continue later by passing the prior run's `task_id` to `form-theory` or `evaluate-novelty`.

## References

- Theorizer: <https://github.com/allenai/asta-theorizer-internal>
- Agent card / schemas: `asta generate-theories card` / `asta generate-theories describe <skill-id>`
- A2A spec: <https://a2a-protocol.org/latest/specification/>
- Shared patterns:
  - `shared-patterns/voice-and-tone.md` *(applies to all user-facing output)*