---
name: AutoDiscovery
description: Check on AutoDiscovery runs, view experiment results, and manage authentication. Use when the user asks about their runs, experiments, discoveries, or wants to check status of an AutoDiscovery job.
metadata:
  internal: true
allowed-tools:
  - Bash(asta autodiscovery *)
  - Bash(asta auth *)
---

# AutoDiscovery

Check on AutoDiscovery runs and view experiment results via the `asta autodiscovery` commands.

## Installation

This skill requires the `asta` CLI:

```bash
# Install/reinstall at the correct version
PLUGIN_VERSION=0.9.1
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
