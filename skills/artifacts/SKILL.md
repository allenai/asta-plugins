---
name: Asta Artifacts
description: Use this skill when the user asks to view, export, or open agent output artifacts — "show me the artifacts", "export the results", "open the report", "convert the task output to HTML", "what did the agent produce", or wants to work with structured outputs from an A2A agent task.
metadata:
  internal: true
allowed-tools:
  - Bash(asta generate-theories task *)
  - Bash(asta artifacts *)
  - Bash(open *)
---

# Asta Artifacts

[Artifacts](https://a2a-protocol.org/latest/specification/#artifacts) are the structured outputs produced by A2A agents during task execution. Each artifact has a name, structured content (sections, markdown), and optionally entities (e.g. papers with Semantic Scholar metadata) and annotations (snippets, facets). They accumulate in the `artifacts[]` field of the task response as the pipeline runs.

`asta generate-theories` is the current Ai2 agent that produces artifacts. Future agents will produce them too — this skill applies to all of them.

## Export workflow

```bash
# 1. Dump the task result to a directory
TASK_DIR=$(mktemp -d)
asta <agent> task "<TASK_ID>" > "$TASK_DIR/task.json"

# 2. Export
OUT_DIR=$(mktemp -d)
asta artifacts --input "$TASK_DIR" --output "$OUT_DIR" --format html   # or --format md

# 3. Open (HTML only)
open "$OUT_DIR/index.html"
```

Tell the user the output path. Works on partial task data too — useful for previewing mid-run.

### HTML (default)

Produces `index.html` with navigation plus one page per artifact, organised into subdirectories by type (theories, extractions, etc.). Best for reading or sharing.

### Markdown (`--format md`)

Produces `index.md` and one `.md` file per artifact; cross-artifact links are rewritten to relative `.md` paths. Best for feeding back into another LLM or storing in version control.

## Reference

- [A2A specification — Artifacts](https://a2a-protocol.org/latest/specification/#artifacts)
- [asta-artifact SDK](https://github.com/allenai/asta-sdk)
