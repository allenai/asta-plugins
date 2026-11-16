---
name: generate-theories
description: Builds literature-grounded scientific theories with Theorizer -- hosted by Asta, with the `theorize` CLI and your own key, or in the coding agent with the library. Use when someone asks to generate theories or hypotheses, to "theorize about" a question, what theories explain something, or to run the Theorizer.
allowed-tools: Bash(theorize *) Bash(asta auth *) Bash(asta generate-theories *) Bash(asta artifacts *) Bash(asta documents *) Bash(s2 *) Bash(asta-papers *) Bash(jq *) Bash(uv tool *) Bash(uv venv *) Bash(uv pip *) Bash(python *) Bash(command -v *) Bash(open *)
---

# Generate theories

Theorizer builds theories from papers. From the question it plans a search and an extraction schema. It extracts findings from each paper's full text, then generates theories whose laws cite those findings. It can then ask the papers which variables the schema missed, and run a pass for each new schema. It can also score how new each law is.

Source: [allenai/asta-theorizer](https://github.com/allenai/asta-theorizer).

## Three ways to run it

- **Hosted.** We pay for it. [hosted.md](hosted.md)
- **CLI.** You pay for it, with your own API key, on this machine. It bakes in our preferences. [cli.md](cli.md), with [papers.md](papers.md) for finding and fetching papers.
- **Library.** You pay for it, in a coding agent: you read the papers and write the findings and theories yourself, and the library gives you the types and keeps the citations straight. [library.md](library.md)

If the project has settled this already (`.asta/mode.json`), use that. Otherwise ask, and don't switch partway through a run.

## The question

- **Pass it as the person wrote it,** with any extra context they gave, word for word. Leave out only instructions about the run itself, such as how many papers or which models.
- **Broad is fine.** A lot of Theorizer's value is finding the variables nobody named. You can offer once to narrow it (what's varied, what's measured, in what setting), but never make that a gate.
- **Ask about the shape.** Theorizer finds laws far more readily when it's told their shape: a production rule like acids + alkalis → salts + water, an IF … THEN law, a threshold equation. The shape goes into the question ("Find IF … THEN laws for …").
- **If it isn't a question the scientific literature can answer,** say so and offer to reframe it.

## The mission statement

Theorizer reads the papers and nothing else. Anything else the theories must answer to goes in as the mission statement, on the plan and on every generation: a focus, experiments a run computed, reproduction verdicts, the gaps to aim at. Left with the bare question, Theorizer ignores them. If you add a mission after the plan, plan again with it before you extract.

## Papers

- **Full text only.** Theorizer extracts from whatever text a paper has, abstracts included, so keep abstract-only papers out (cli.md and papers.md say how).
- **Say what the theories rest on:** how many papers out of the target, how many were tried, and why the rest have no full text.
- **The person's own papers,** a folder, files or a glob, can be the whole corpus or add to a search.

## Checks

- **The plan** (CLI and hosted): check that it has a search query and a schema before going on. A failed model call can leave an empty plan behind.
- **The extraction, before you generate:** which papers failed and why, and which had nothing to extract. A paper with nothing in it is a result, not a failure. Don't generate from a fraction of the papers without saying so.
- **Check in after the first theories.** Discovering variables and running the schema passes cost several times the first pass.

## Reading the theories

- **Call a theory by its name,** everywhere.
- **Cluster them by the explanation they give.** Theories from different schemas often restate each other, and a cluster several schemas reached rests on more of the evidence. For each cluster, say what it's about plainly, then technically, and why the person should care. Point them to the clusters worth reading first.
- **A theory's text can't be edited.** If its figures overstate their evidence, say which theory, in your own words.
