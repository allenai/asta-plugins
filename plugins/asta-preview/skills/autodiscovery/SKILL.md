---
name: AutoDiscovery
description: Create, configure, and monitor AutoDiscovery runs. Use when the user asks about their runs, experiments, discoveries, wants to check status, or wants to start a new discovery run.
metadata:
  internal: true
allowed-tools:
  - Bash(asta autodiscovery *)
  - Bash(asta auth *)
  - Read(*)
  - Write(*.json)
  - TaskOutput
---
# AutoDiscovery

Create, configure, and monitor AutoDiscovery runs via the `asta autodiscovery` commands. AutoDiscovery is an AI-driven scientific discovery platform that runs iterative experiments guided by Bayesian surprise and MCTS optimization.

## Installation

This skill requires the `asta` CLI:

```bash
# Install/reinstall at the correct version
PLUGIN_VERSION=0.10.1
if [ "$(asta --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" != "$PLUGIN_VERSION" ]; then
  uv tool install --force git+https://github.com/allenai/asta-plugins.git@v$PLUGIN_VERSION
fi
```

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/)

## Authentication

AutoDiscovery uses the shared Asta authentication. If you get an auth error, run `asta auth login` first.

## Viewing Runs

- **`asta autodiscovery runs`** — List all runs for the authenticated user
- **`asta autodiscovery run <runid>`** — Get full details for a specific run
- **`asta autodiscovery status <runid>`** — Check current execution status of a run
- **`asta autodiscovery credits`** — Show credit balance (granted/consumed/pending/available)

## Viewing Experiments

- **`asta autodiscovery experiments <runid>`** — List all experiments in a run with status, surprise scores, priors, posteriors, and hypotheses
- **`asta autodiscovery experiment <runid> <experiment_id>`** — Get full details for a single experiment. The experiment_id format is like `node_0_0`, `node_1_0`, etc.

## Output Formats

All commands support `--format json` (default) and `--format text`:

```bash
asta autodiscovery runs --format text
asta autodiscovery experiments <runid> --format text
```

Use `--format text` when presenting results directly to the user.

## Interpreting Results

- **Status values**: RUNNING, SUCCEEDED, FAILED, CANCELLED, DELETED, PENDING, UNKNOWN
- **Surprise**: A normalized surprisal score. Higher = more surprising relative to the prior belief.
- **Prior/Posterior**: Mean of the prior and posterior belief distributions. A large shift indicates the experiment changed the model's beliefs significantly.
- **is_surprising**: Boolean flag set when surprise exceeds the configured threshold.

## Presenting Results

When showing results to the user:
1. Run the appropriate command
2. Present results in a clean, readable format
3. Highlight anything notable (surprising experiments, failed runs, etc.)
4. Offer to drill deeper into specific runs or experiments

When showing experiment details, focus on the hypothesis, analysis, and review fields. Show code and code_output only if specifically asked.

---

## Creating Runs

### Workflow A: New Run (create, upload, configure, submit)

```bash
# 1. Create an empty run
RUNID=$(asta autodiscovery create)
echo "Created run: $RUNID"

# 2. Upload dataset files
asta autodiscovery upload "$RUNID" path/to/dataset.csv path/to/other_data.json

# 3. Save metadata configuration
asta autodiscovery metadata "$RUNID" --file metadata.json

# 4. Submit for execution
asta autodiscovery submit "$RUNID"
```

### Workflow B: Fork an Existing Run

```bash
# 1. Fork (copies metadata + datasets server-side)
NEW_RUNID=$(asta autodiscovery fork <existing-runid>)

# 2. Optionally get and modify metadata
asta autodiscovery metadata-get "$NEW_RUNID" > metadata.json
# Edit metadata.json...
asta autodiscovery metadata "$NEW_RUNID" --file metadata.json

# 3. Submit
asta autodiscovery submit "$NEW_RUNID"
```

## Metadata Schema (metadata.json)

Build this JSON file for the user based on their research goals and datasets.

```json
{
  "name": "Run Name",
  "description": "Context about the data: its origin, collection methods, known gaps or biases.",
  "domain": "Research domain (e.g., Ornithology, Materials Science, NLP)",
  "intent": "High-level guidance to condition exploration without specifying exact hypotheses.",
  "datasets": [
    {
      "name": "filename.csv",
      "description": "What this dataset contains and what each column/field represents.",
      "content_type": "text/csv",
      "file_size_bytes": 1048576,
      "is_preloaded": false
    }
  ],
  "n_experiments": 20,
  "exploration_weight": 3.0,
  "mcts_selection": "ucb1_recursive",
  "surprisal_width": 0.3,
  "evidence_weight": 2.0
}
```

### Required Fields for Submission

- **name**: A descriptive name for the run
- **datasets**: At least one dataset entry (matching an uploaded file)
- **n_experiments**: How many experiments to run (1 credit = 1 experiment)

### Field Guide

#### Descriptive Fields

| Field | Purpose | Tips |
|-------|---------|------|
| **name** | Short title for the run | Keep it descriptive but concise |
| **description** | Dataset context for the AI agent | Describe data provenance, collection method, known gaps. The agent uses this to generate better hypotheses. |
| **domain** | Research field | Helps the agent contextualize hypotheses (e.g., "Genomics", "Climate Science") |
| **intent** | Exploration guidance | Steer exploration without being too specific. Example: "Focus on how temperature affects yield" rather than "Test if temperature > 30C reduces yield by 20%" |

#### Dataset Entries

Each entry in `datasets` should match an uploaded file:

| Field | Description |
|-------|-------------|
| **name** | Filename as uploaded (must match exactly) |
| **description** | What the data contains, column meanings, units |
| **content_type** | MIME type: `text/csv`, `application/json`, `text/tab-separated-values`, etc. |
| **file_size_bytes** | File size in bytes (for display; upload validates independently) |
| **is_preloaded** | Always `false` for CLI uploads |

#### Experiment Configuration

| Field | Default | Range | Description |
|-------|---------|-------|-------------|
| **n_experiments** | - | 1-500 | Number of experiments. Each costs 1 credit. Start with 10-20 for exploration, 50-100 for thorough investigation. |
| **exploration_weight** | 1.0 | 0.1-10 | Higher = broader exploration across hypothesis space (3-5). Lower = deeper refinement of promising hypotheses (0.5-1). |
| **mcts_selection** | `"ucb1_recursive"` | `"ucb1_recursive"` or `"pw"` | Search strategy. UCB1 Recursive is the default and works well for most cases. Progressive Widening (`"pw"`) can help with very large hypothesis spaces. |
| **surprisal_width** | 0.5 | 0.0-1.0 | Threshold for what counts as "surprising". Higher = only dramatic findings (0.7-1.0). Lower = subtle discoveries too (0.1-0.3). |
| **evidence_weight** | 1.0 | 0.1-10 | How much to trust experimental results. Higher = relies heavily on data (2-5). Lower = more cautious, skeptical (0.3-0.8). |

### Example Configurations

**Quick exploration** (new dataset, broad survey):
```json
{
  "n_experiments": 15,
  "exploration_weight": 4.0,
  "surprisal_width": 0.3,
  "evidence_weight": 1.5
}
```

**Deep investigation** (known domain, specific questions):
```json
{
  "n_experiments": 50,
  "exploration_weight": 1.0,
  "surprisal_width": 0.5,
  "evidence_weight": 3.0
}
```

**Sensitive/noisy data** (high bar for surprise, cautious inference):
```json
{
  "n_experiments": 30,
  "exploration_weight": 2.0,
  "surprisal_width": 0.7,
  "evidence_weight": 0.5
}
```

## Building metadata.json Interactively

When helping a user build metadata.json:

1. **Ask about their research goal** - what question do they want to answer?
2. **Inspect their datasets** - read the files to understand columns, data types, size
3. **Draft the metadata** - fill in name, description, domain, intent based on what you learn
4. **Suggest experiment parameters** - based on dataset size and research goal
5. **Write the file** - save as `metadata.json` (or user-specified path)
6. **Validate** - ensure dataset names match uploaded filenames, n_experiments is reasonable given credit balance

### Inspecting Datasets

Before writing metadata, read the user's data files to understand them:

```bash
# For CSV files - check headers and sample rows
head -5 dataset.csv

# For JSON files - check structure
python3 -c "import json; d=json.load(open('data.json')); print(type(d), len(d) if isinstance(d, list) else list(d.keys())[:10])"
```

Use this information to write accurate `description` fields for both the run and individual datasets.

## Notes

- Check credits before suggesting n_experiments: `asta autodiscovery credits`
- The `submit` command will show credit cost and ask for confirmation
- Dataset upload uses presigned URLs - files go directly to GCS, not through the gateway
- Maximum file size is 50GB per file (100GB with special permission)
- After submission, monitor with: `asta autodiscovery status <runid>`
