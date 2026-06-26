---
name: artifacts
description: Use this skill to export and open A2A agent task outputs — "export the task results", "convert the task output to HTML", or work with the structured artifacts produced by an A2A agent task run.
metadata:
  internal: true
allowed-tools: Bash(asta * task *) Bash(asta artifacts *) Bash(asta documents *) Bash(open *)
---

# Asta Artifacts

[Artifacts](https://a2a-protocol.org/latest/specification/#artifacts) are the structured outputs produced by A2A agents. They accumulate in the `artifacts[]` field of the task response.

## Export

```bash
# 1. Dump task result
TASK_DIR=$(mktemp -d)
asta <agent> task "<TASK_ID>" > "$TASK_DIR/task.json"

# 2. Export (caller decides output dir and format)
asta artifacts --input "$TASK_DIR" --output "$OUT_DIR" --format md
```

Produces per-artifact files organized by subtype, plus `index.md`, `references.bib`, and `manifest.json`.

Works on partial task data too — useful for previewing mid-run.

## Formats

- `--format md` — markdown, one `.md` per artifact. Cross-artifact links use relative `.md` paths. Best for LLM consumption, version control, and indexing into asta-documents.
- `--format html` — self-contained HTML with `index.html`. Open with `open "$OUT_DIR/index.html"`. Best for reading or sharing.

## Path convention (when invoked by another skill)

When another skill hands off to this one to export a run, default to writing
under:

```
.asta/<invoking-skill>/<slug>/
```

Where `<slug>` is `YYYY-MM-DD-<short-query-slug>` — date-first for
chronological ordering, short-slug derived from the primary input (query,
topic, etc.). Register the exported artifacts with asta-documents into a
single per-skill aggregate index at `.asta/<invoking-skill>/index.yaml` so
consumers can search across all runs.

Example (theorizer run):

```
.asta/generate-theories/2026-04-17-media-polarization/   # per-run outputs
.asta/generate-theories/index.yaml                        # aggregate index
```

## Indexing with asta-documents

After export, read `manifest.json` and register each entry with `asta documents add`. Each manifest entry has: `name`, `description`, `filename`, `mime_type`, and optionally `subtype` and `metadata`. Map these directly to:

- `file://<absolute-path-to-OUT_DIR>/<filename>` as the URL
- `--name` from `name`
- `--summary` from `description` (fall back to `name`)
- `--mime-type` from `mime_type`
- `--tags` from `subtype` if present
- `--extra` from `metadata` as JSON if present

Use `--root <dir>` to target a scoped index (e.g. per-agent) instead of the default `.asta/documents/`.
