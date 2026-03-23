---
name: Asta Literature Reports
description: This skill should be used when the user asks to "generate a report", "write a literature review", "create a comprehensive summary", "synthesize the literature", or needs a detailed written report on an academic topic. Use this for thorough, multi-paper synthesis tasks that produce written deliverables. Can work with existing paper-finder results or launch new searches.
metadata:
  internal: true
allowed-tools:
  - Bash(asta literature find *)
  - Bash(asta literature report *)
  - Read(.asta/literature/*)
  - TaskOutput
---

# Literature Report Generation

Generate comprehensive literature reports by finding relevant papers and synthesizing them into a structured written report.

## When to Use This Skill

- User asks for a literature review or comprehensive report
- Task requires synthesizing multiple papers into a coherent narrative
- User wants a written deliverable (not just a list of papers)
- Topic requires deep exploration with citations and evidence
- User has existing paper-finder results and wants a comprehensive report from them

## Workflow

### 1. Check for Existing Results

**If the user provides an existing paper-finder results file:**
- Skip to step 3, using that file as `-i`

**If no existing results file:**
- Proceed to step 2

### 2. Find Papers

```bash
asta literature find 'query' --timeout 300 -o .asta/literature/find/YYYY-MM-DD-topic-slug.json
```

Note the output path from the command.

### 3. Generate the Report

```bash
asta literature report \
  -i .asta/literature/find/YYYY-MM-DD-topic-slug.json \
  -o .asta/literature/report/YYYY-MM-DD-topic-slug.md
```

The command prints progress to stderr and the report path when done.

### 4. Confirm and Share

- Read the saved report file and share the key findings with the user
- Tell the user the file path so they can open it

## Error Handling

- **Authentication error**: Run `asta auth login` and retry
- **Timeout**: Pass a larger `--timeout` value (default is 360s)
- **No papers found**: Suggest refining the query and re-running `asta literature find`
