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

The CLI is generated from the agent card — every skill, flag, and default.
Discover the surface yourself:

- `asta generate-theories --help` — list subcommands.
- `asta generate-theories card` — full agent card.
- `asta generate-theories describe <skill-id>` — input schema for one skill.

## Flows

| User wants                                          | Run                                |
|-----------------------------------------------------|------------------------------------|
| End-to-end theory generation from a question        | `literature-theory-generation`     |
| Same, with their own pre-collected papers           | `literature-theory-generation` + `--paper-store @file.json` |
| Just find + extract evidence (no theories yet)      | `find-and-extract`                 |
| Theorize from existing extraction results           | `form-theory`                      |
| Score novelty on existing theories                  | `evaluate-novelty`                 |
| Resume a failed/partial extraction run              | `resume-extraction`                |

## How to dispatch

1. **Classify** the user's request into one of the 6 rows above.
2. If unclear, fire one `AskUserQuestion` with the rows as options. If
   `AskUserQuestion` isn't available, list them in chat and wait for a
   reply.
3. Run `asta generate-theories describe <skill-id>` to see required + key
   optional fields.
4. Identify which required fields the user already supplied. For any
   missing required fields and the 2–3 most impactful optionals (papers,
   objective, novelty), **ask one chat question** unless the user said
   "use defaults" — then submit immediately.
5. **Submit.** The skill-id is the subcommand — there is no `submit`
   verb. Each schema property maps to a `--kebab-case` flag. For example:

   ```bash
   asta generate-theories literature-theory-generation \
       --theory-query "<question>" \
       --max-papers-to-retrieve 30 \
       --no-do-qualified-novelty-evaluation
   ```

   Object-typed flags accept inline JSON, `@path/to.json`, or a URI
   (`file://`, `s3://`, `https://`). The CLI streams progress to stderr
   and prints the final Task JSON to stdout when the task terminates.
   The CLI handles the polling (5s/15s/60s backoff) — don't write your
   own loop. Use `--no-wait` only if the user explicitly asked for
   fire-and-forget. In an interactive session you can run the submit
   with `Bash(..., run_in_background=true)` and wait for the completion
   notification; in headless / batch contexts run foreground so the
   final Task lands in stdout before your turn ends.

## Defaults worth knowing

These are schema defaults — don't repeat them unless the user wants to tune:

- `max_papers_to_retrieve`: 10 (~3–8 min). Bump to 30 for medium runs,
  100 for full coverage (15–25 min).
- `generation_objective`: `accuracy-focused`. If the user emphasizes
  *novelty* or *new theories*, set `novelty-focused` without asking.
- `do_qualified_novelty_evaluation`: `true`. Adds 30–60 min and ~$5–10.
  Skip only if the user wants fast iteration.

## After the task completes

Hand off to the **Asta Artifacts** skill to export and index the result —
it owns the path convention, manifest, and asta-documents registration.
Pass `generate-theories` as the invoking skill and a slug shaped
`YYYY-MM-DD-<short-query-slug>` derived from the theory query.

Then write, in chat, in this order:

1. **Where it lives** — the indexed path + the `asta documents search`
   command + `open <absolute path>`. Use absolute paths.
2. **One-paragraph synthesis** — 2–4 fresh sentences. What do the
   theories collectively argue? Where do they converge / diverge? What's
   the headline "so what"? Read the theories; don't template.
3. **Table of theories** — one row per theory: name + 2–3 sentence core
   idea. Add a *novelty* column if novelty was scored.

No "let me know if you'd like…" tail — the search/open links cover it.

## Resumption / errors

- `state=input-required` → CLI prints a `Continue with: …` hint. Relay
  to the user; resend with `asta generate-theories send-message
  --task-id <id> --context-id <ctx> '<reply>'` and re-run the wait.
- `state=failed` → report `status.message` and stop.
- Network/protocol errors exit non-zero with a JSON `{error: …}` on
  stderr.

## References

- Theorizer: <https://github.com/allenai/asta-theorizer>
- Agent card / schemas: `asta generate-theories card` /
  `asta generate-theories describe <skill-id>`
- A2A spec: <https://a2a-protocol.org/latest/specification/>
