# Workflow: local

Run AutoDiscovery on the user's own machine via the `auto-discovery` CLI, which the `asta-autodiscovery` package installs. No Asta authentication or credits are required — experiments execute locally and results are stored locally.

## Installation

Install (or upgrade) the local CLI with `uv`:

```bash
if ! command -v auto-discovery >/dev/null 2>&1; then
  uv tool install asta-autodiscovery
fi
```

**Prerequisites:** Python 3.13+ and [uv package manager](https://docs.astral.sh/uv/).

Verify the install:

```bash
auto-discovery --version
```

If the command is not on PATH after install, remind the user to run `uv tool update-shell` (or open a new shell) so `~/.local/bin` is picked up.

## Discovering available commands

The CLI is distributed independently of this skill. Before answering questions about what it can do, run:

```bash
auto-discovery --help
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
Model names need a provider prefix (`openai/`, `anthropic/`, `vertex_ai/`). Every model flag defaults to Gemini, so when using another provider, set all three.

If the user has an `OPENAI_API_KEY` environment variable set, use GPT-6 Luna (about 6 to 8 minutes and $0.10 per experiment):
```
--model openai/gpt-6-luna
--belief_model openai/gpt-6-luna
--vision_model openai/gpt-6-luna
```

If the user has an `ANTHROPIC_API_KEY` environment variable set, use Claude Opus 5 (about 10 to 15 minutes and $2 per experiment).
```
--model anthropic/claude-opus-5
--belief_model anthropic/claude-opus-5
--vision_model anthropic/claude-opus-5
```
Leave `--dedupe` off with an Anthropic key only: its embeddings use an OpenAI model.

If the user wishes to use Gemini-family models (the default), prompt them to create a service account key using [these instructions](https://docs.cloud.google.com/iam/docs/keys-create-delete),
and save it to a local file. Then set these environment variables:
```
export GOOGLE_APPLICATION_CREDENTIALS=<path-to-key-file>
export VERTEXAI_PROJECT=<user's project-id>
export VERTEXAI_LOCATION=global
```

### Starting a run

Unless otherwise specified, start every local run with `scripts/run_relaxed.py` rather than calling `auto-discovery` directly, whichever provider is used. AutoDiscovery's own reviewer fails an experiment for any gap against its plan, so many sound experiments are thrown out; this script runs AutoDiscovery with a reviewer that fails an experiment only when its main result is wrong or untested. It takes the same arguments as `auto-discovery`:

```bash
"$(uv tool dir)/asta-autodiscovery/bin/python" -I scripts/run_relaxed.py <auto-discovery arguments>
```

In our tests it raised GPT-6 Luna's pass rate from about a third to nearly all experiments, and cost less per usable experiment. It prints `experiment_reviewer: relaxed system message active` when it starts. More experiments pass, so read the results rather than trusting the pass count. Tested with `asta-autodiscovery` 1.0.1.

### Known behaviours

- A run whose model calls all fail (a missing or invalid key, no quota) does not stop on its own; it retries indefinitely and writes a large log. Watch the first few minutes of a new run and stop it if every call errors.
- A model's safety filter can stop a response partway through. AutoDiscovery does not retry and records no experiment, so a run can end almost immediately with exit status 0 and no experiments. If a run ends with "No new experiment generated", search the log for `content_filter`.

## Result Summarization
See `assets/interpreting-results.md` for instructions on how to report a result back to the uesr
