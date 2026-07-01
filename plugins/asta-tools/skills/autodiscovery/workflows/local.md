# Workflow: local

Run AutoDiscovery on the user's own machine via the `asta-autodiscovery` CLI. No Asta authentication or credits are required — experiments execute locally and results are stored locally.

## Installation

Install (or upgrade) the local CLI with `uv`:

```bash
if ! command -v asta-autodiscovery >/dev/null 2>&1; then
  uv tool install asta-autodiscovery
fi
```

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/).

Verify the install:

```bash
asta-autodiscovery --version
```

If the command is not on PATH after install, remind the user to run `uv tool update-shell` (or open a new shell) so `~/.local/bin` is picked up.

## Discovering available commands

The CLI is distributed independently of this skill. Before answering questions about what it can do, run:

```bash
asta-autodiscovery --help
asta-autodiscovery <subcommand> --help
```

Use the help output as the source of truth for available subcommands, flags, and arguments. Do not assume the local CLI mirrors the hosted `asta autodiscovery` surface — they may diverge.

## Configuring a run

The CLI requires, at a minimum, the following information:

- A name for the run (`--name`)
- One or more datasets (`<path> ...`)
- An overall description (`--description` or a `--dataset_description` for each dataset)
- A high-level guidance to steer exploration (`--intent`)
- Experiment parameters (`--n_experiments`, `--n_threads`)
- An output directory (`--out_dir`)

When helping the user build configuration:

1. Ask about their research goal.
2. Inspect their datasets (`head -5 file.csv`, check JSON structure, etc.) to understand columns, units, and size.
3. Propose a dataset description and prompt them to add context about the dataset's origin and motivation
3. Suggest < 10 experiments for a trial run, more for an in-depth analysis

### Credentials
If the user has an `OPENAI_API_KEY` environment variable set, use the following flags to use GPT-family models:
```
--model gpt-4o
--belief_model gpt-4o-mini
--vision_model gpt-4o
```

If the user wishes to use Gemini-family models (the default), prompt them to create a service account key using [these instructions](https://docs.cloud.google.com/iam/docs/keys-create-delete),
and save it to a local file. Then set these environment variables:
```
export GOOGLE_APPLICATION_CREDENTIALS=<path-to-key-file>
export VERTEX_PROJECT_ID=<user's project-id>
export VERTEX_LOCATION=global
```

## Result Summarization
See `assets/interpreting-results.md` for instructions on how to report a result back to the uesr
