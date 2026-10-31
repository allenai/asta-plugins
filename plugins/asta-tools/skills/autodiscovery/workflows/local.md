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

If the user has an `OPENAI_API_KEY` environment variable set, use the following flags to use GPT-family models:
```
--model openai/gpt-4o
--belief_model openai/gpt-4o-mini
--vision_model openai/gpt-4o
```

If the user has an `ANTHROPIC_API_KEY` environment variable set, use the following flags to use Claude models:
```
--model anthropic/claude-sonnet-5-5
--belief_model anthropic/claude-sonnet-5-5
--vision_model anthropic/claude-sonnet-5-5
```
Leave `--dedupe` off with an Anthropic key only: its embeddings use an OpenAI model.

If the user wishes to use Gemini-family models (the default), prompt them to create a service account key using [these instructions](https://docs.cloud.google.com/iam/docs/keys-create-delete),
and save it to a local file. Then set these environment variables:
```
export GOOGLE_APPLICATION_CREDENTIALS=<path-to-key-file>
export VERTEXAI_PROJECT=<user's project-id>
export VERTEXAI_LOCATION=global
```

### Packages available to experiment code

The `--backend` flag decides where the generated experiment code runs, and so which packages it can import. Installing a package into the CLI's own environment (`uv tool install asta-autodiscovery --with <package>`) does not reach the experiments under any backend.

| Backend | Where experiment code runs | Python packages preinstalled |
|---|---|---|
| `process` (default) | A fresh virtual environment the CLI builds for each run | ipython, numpy, pandas, matplotlib, matplotlib-inline, seaborn, scikit-learn, scipy, statsmodels. The CLI has no option to add to this list. |
| `local` | The first `python` on the user's `PATH` | Whatever that environment has installed |
| `modal` | A Modal sandbox (needs a Modal account and a cloud bucket) | Same list as `process` |

Experiment code can also install packages itself while it runs. AutoDiscovery gives the generated code an `install(package)` helper and tells the planner that packages can be installed. Under `process`, an install lasts only for that one code execution, so the code has to install again each time, and it needs network access. In practice the models often do not use it: when an import fails they tend to write the method by hand or drop it instead.

When the analysis depends on a package outside the preinstalled list (survey statistics with `svy` or `samplics`, for example), make sure it is there by using the `local` backend with a virtual environment that holds the packages, activated in the shell that starts the run:

```bash
uv venv ~/.autodiscovery-env --python 3.13
VIRTUAL_ENV=~/.autodiscovery-env uv pip install numpy pandas matplotlib seaborn scikit-learn scipy statsmodels <extra packages>
source ~/.autodiscovery-env/bin/activate
auto-discovery --backend local ...
```

The CLI itself still runs from its own tool environment; only the experiment code uses the activated one. Without an activated environment, `local` runs whichever `python` the shell finds, and fails if there is none. With `local` the experiment code runs as the user, with no isolation: it can read and write anything the user can.

R packages are installed into the system R (`install.packages(...)`) and are visible to experiments under both `process` and `local`, because experiment code calls R as a subprocess. The `modal` sandbox has no R.

### Known behaviours

- A run whose model calls all fail (a missing or invalid key, no quota) does not stop on its own; it retries indefinitely and writes a large log. Watch the first few minutes of a new run and stop it if every call errors.
- A model's safety filter can stop a response partway through. AutoDiscovery does not retry and records no experiment, so a run can end almost immediately with exit status 0 and no experiments. If a run ends with "No new experiment generated", search the log for `content_filter`. This has been seen with Claude Opus 5.5 on infectious-disease data; Claude Opus 5 (`anthropic/claude-opus-5`) and Sonnet 5.5 ran the same data without it.
- The experiment reviewer rejects many experiments, often for incomplete reporting against the plan rather than a wrong result, and allows only one revision. Pass rates of 20–50% are normal, and the CLI has no setting to change the reviewer.

## Result Summarization
See `assets/interpreting-results.md` for instructions on how to report a result back to the uesr
