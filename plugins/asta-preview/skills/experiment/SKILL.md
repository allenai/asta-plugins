---
name: Asta Software Experiment Runner
description: Run scientific (software) experiments. Use when the user asks to "run an experiment", "run an investigation", or "research with Asta." Also use this skill to analyze experimental data generate a research report from it. The user may refer to this system by its internal project name, "Panda."
metadata:
  internal: true
allowed-tools:
  - Bash(asta experiment *)
  - Bash(mkdir -p .asta/experiment/*)
  - Read(.asta/experiment/*)
  - TaskOutput
---
# Run Experiments

Run a computational experiment. Given a research question that can be answered via software,
this skill will write and run the necessary software and generate a report on the results.

This skill can also be used to analyze experimental data and generate a research report from it, even if the experiment itself was not run by Asta. In that case, the user can provide the experimental data as a file input, and Asta will analyze it and generate a report.

## Installation

This skill requires the `asta` CLI:

```bash
# Install/reinstall at the correct version
PLUGIN_VERSION=0.12.0
if [ "$(asta --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" != "$PLUGIN_VERSION" ]; then
  uv tool install --force git+https://github.com/allenai/asta-plugins.git@v$PLUGIN_VERSION
fi
```

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/)


## Workflow

The user will either:
1. describe the research task (TASK) and (optionally) background knowledge (BACKGROUND_KNOWLEDGE)
   or
2. provide paths to *files* that contain
   a. the task (TASK_FILE)
   b. (optionally) the background knowledge (BACKGROUND_KNOWLEDGE_FILE)

### Default Output Locations

**IMPORTANT**: Always specify output locations to keep experiments organized in `.asta/experiment/`:

- **OUTPUTS_DIR**: `.asta/experiment/<YYYY-MM-DD-slug>/` where:
  - `YYYY-MM-DD` is the current date
  - `slug` is a short descriptive name derived from the task (e.g., "french-translation", "gpt4-eval")
- **RESULT_FILE**: `<OUTPUTS_DIR>/result.json`

**Example directory structure:**
```
.asta/experiment/
├── 2024-01-15-french-translation/
│   ├── result.json
│   └── [experiment outputs]
└── 2024-01-16-model-comparison/
    ├── result.json
    └── [experiment outputs]
```

The user may optionally override these locations by providing:
3. a custom directory for experimental outputs (OUTPUTS_DIR)
4. a custom path for the result summary JSON (RESULT_FILE)

### Task and Background Knowledge

If the user describes a task and (optionally) provides background knowledge, then run as follows:

**With default output locations (recommended):**
```bash
# Create output directory with date and slug
OUTPUTS_DIR=".asta/experiment/$(date +%Y-%m-%d)-<task-slug>"
mkdir -p "$OUTPUTS_DIR"

asta experiment \
  --task "TASK" \
  --background_knowledge "BACKGROUND_KNOWLEDGE" \
  --force_report \
  --outputs_dir "$OUTPUTS_DIR" \
  --result_file "$OUTPUTS_DIR/result.json"
```

**Example:**
```bash
# Task: Assess GPT-4 translation quality
OUTPUTS_DIR=".asta/experiment/$(date +%Y-%m-%d)-gpt4-french-translation"
mkdir -p "$OUTPUTS_DIR"

asta experiment \
  --task "Perform an experiment to assess how good gpt-4o is at translating into French. Use just 5 test examples." \
  --force_report \
  --outputs_dir "$OUTPUTS_DIR" \
  --result_file "$OUTPUTS_DIR/result.json"
```

**With custom output locations (if user specifies):**
```bash
asta experiment \
  --task "TASK" \
  --background_knowledge "BACKGROUND_KNOWLEDGE" \
  --force_report \
  --outputs_dir "/custom/path/experiments/" \
  --result_file "/custom/path/result.json"
```
### Task and Background Knowledge Files

When the user provides files containing the task and background knowledge:

**With default output locations (recommended):**
```bash
# Create output directory with date and slug (derived from task filename or content)
OUTPUTS_DIR=".asta/experiment/$(date +%Y-%m-%d)-<task-slug>"
mkdir -p "$OUTPUTS_DIR"

asta experiment \
  --task_file "TASK_FILE" \
  --background_knowledge_file "BACKGROUND_KNOWLEDGE_FILE" \
  --force_report \
  --outputs_dir "$OUTPUTS_DIR" \
  --result_file "$OUTPUTS_DIR/result.json"
```

**Example:**
```bash
# Files: my_project/task.txt, my_project/background_knowledge.txt
OUTPUTS_DIR=".asta/experiment/$(date +%Y-%m-%d)-custom-experiment"
mkdir -p "$OUTPUTS_DIR"

asta experiment \
  --task_file "my_project/task.txt" \
  --background_knowledge_file "my_project/background_knowledge.txt" \
  --force_report \
  --outputs_dir "$OUTPUTS_DIR" \
  --result_file "$OUTPUTS_DIR/result.json"
```

**With custom output locations (if user explicitly specifies paths):**
```bash
asta experiment \
  --task_file "my_project/task.txt" \
  --background_knowledge_file "my_project/background_knowledge.txt" \
  --force_report \
  --outputs_dir "my_project/experiments/" \
  --result_file "my_project/result.json"
```

### Notes

- **Output Directory**: Always create `.asta/experiment/<YYYY-MM-DD-slug>/` directory before running the experiment using `mkdir -p`
- **Task Slug**: Create a short descriptive slug from the task (e.g., "gpt4-translation", "model-comparison"). Keep it lowercase with hyphens.
- **Result File**: Always save to `<OUTPUTS_DIR>/result.json` for consistency
- **Background Knowledge**: Optional - can be omitted if not provided by user
- **Custom Paths**: If user explicitly provides custom output paths, use those instead of defaults
- Always return the result to the user and inform them where outputs were saved



