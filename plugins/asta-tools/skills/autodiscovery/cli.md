# AutoDS with the CLI

You pay for it, through your own API key. It runs on this computer with `auto-discovery`, and the model calls go to whoever your key is with. Nothing goes to Asta.

## Install

```bash
command -v auto-discovery || uv tool install --python 3.13 asta-autodiscovery
auto-discovery --version
auto-discovery --help        # the source of truth for flags; it can differ from the hosted service
```

Keep `--python 3.13`: on a newer Python, one dependency (`h5py`) has no prebuilt package and the install fails partway through. If the command isn't found after installing, run `uv tool update-shell` or open a new shell.

## Keys and models

Pass `--model <provider>/<model>` (or set `AUTODISCOVERY_MODEL`); the belief and vision models fall back to it. With both keys, use OpenAI unless the person asks otherwise. Our preferences:

| Key | Model | Per experiment |
|---|---|---|
| `OPENAI_API_KEY` | `openai/gpt-6-luna` | about $0.01 and 1 to 2 minutes of wall time on a small table (two run at once); up to $0.10 and 6 to 8 minutes on bigger data |
| `ANTHROPIC_API_KEY` | `anthropic/claude-opus-5` | about 10 to 15 minutes and $2 |

`--dedupe` needs an embedding model (`--embedding_model openai/text-embedding-3-large`), so with only an Anthropic key leave it off. For Gemini, the person makes a Google Cloud service-account key and sets `GOOGLE_APPLICATION_CREDENTIALS`, `VERTEXAI_PROJECT` and `VERTEXAI_LOCATION=global`.

Never ask for a key in chat, because it would stay in the transcript. The person sets it in their shell.

## A run

`<tools>` is the folder `uv tool dir` prints; write it out in full, since a command that starts with `$(…)` can't be matched by a permission rule. Run it through `scripts/run_relaxed.py`, which takes the same arguments as `auto-discovery` and also passes on the resume and seed flags, which plain `auto-discovery` doesn't have. Its reviewer fails an experiment only when the main result is wrong or untested, where AutoDS's own fails it for any gap against its plan. On some data that took the pass rate from about a third to nearly all, so read the experiments rather than trusting the count. It prints `experiment_reviewer: relaxed system message active` when it starts.

```bash
<tools>/asta-autodiscovery/bin/python -I <this skill>/scripts/run_relaxed.py <data files> \
  --name "<short name>" \
  --intent "<the prompt>" \
  --dataset_description "$(cat <file>.description.md)" \
  --n_experiments 50 \
  --model <model> \
  --out_dir <run folder>
```

Run it from the project folder, so the data files and `--out_dir` are relative to it.

- `--n_experiments` on a new run is the number of experiments, not counting the data-loading node, and seeds count toward it.
- `--dataset_description` is a string, given once per file, in the same order as the files.
- Each experiment lands in `<run folder>` as `mcts_node_*.json`, with the usage in `llm_usage_events.jsonl`. That has tokens, not cost. For an upper bound on the cost so far, ignoring cache discounts:

  ```bash
  <tools>/asta-autodiscovery/bin/python -I -c 'import json,sys,litellm; p=litellm.model_cost; print(round(sum(e["usage"]["prompt_tokens"]*p[e["model"]]["input_cost_per_token"]+e["usage"]["completion_tokens"]*p[e["model"]]["output_cost_per_token"] for e in map(json.loads,open(sys.argv[1]))),4))' <run folder>/llm_usage_events.jsonl
  ```
- It's done when the log ends with `HTML report: <run folder>/report/index.html` and `ps -axo command | grep '[r]un_relaxed.py'` is empty.
- A run of 50 can take an hour or more. Run it in the background (`nohup <command> > run.log 2>&1 &`; macOS has no `setsid`) and check the log. In a hosted sandbox, wait for it inside the turn.

## The next round

Seeds only take on a new run, so each round is a new run, seeded with the picks. Write them to a JSON list of `{"hypothesis", "experiment_plan"}` copied verbatim from their nodes, and add `--warmstart_experiments <file> --n_warmstart <count>` to a fresh `--out_dir`. The seeds run first, as the first children of `node_1_0`, but not in the file's order, so match them by hypothesis.

Growing one run, without seeds, also works, but only this way:

```bash
cp -Rp <run> <run>-backup
mkdir <run>-flat && find <run> -maxdepth 1 -type f ! -name args.json -exec cp -p {} <run>-flat/ \;
<the same command> --continue_from_dir <run>-flat --out_dir <run> --n_experiments <existing + k + 1>
```

Pointing `--continue_from_dir` at the run's own folder fails after it has overwritten `args.json`, and pointing it at the untouched folder fails on `rich_outputs/`. On a resume, `--n_experiments` is the new total, counting the data-loading node, so add 1. The usage log is overwritten, so add up its cost first. Seeds given here are silently ignored.

## Watch the first minute

- **Check that the files appear.** `mcts_node_1_0.json` comes within about a minute, and the first experiment 2 to 4 minutes after. A bad key ends the run in under a second with no experiments, and the report still says SUCCEEDED. The log has `AuthenticationError`.
- **If a safety filter cuts a response off,** AutoDS records nothing and can end at once, with exit status 0 and "No new experiment generated". Search the log for `content_filter`. We've seen it with `anthropic/claude-opus-5-5` on infectious-disease data, where `anthropic/claude-opus-5` ran the same data to the end.
- **Tracebacks in the log** are usually from the generated code, which the agents fix. Ignore them unless an experiment fails. If several fail the same way, say so rather than letting the budget drain.
