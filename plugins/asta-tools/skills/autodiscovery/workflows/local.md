# AutoDS, local

On this computer. Nothing goes to Asta. Two ways: the `auto-discovery` CLI with your own API key, or the library in a coding agent, where the agent is the model.

## With the CLI

You pay for it, through your own API key. It runs on this computer with `auto-discovery`, and the model calls go to whoever your key is with. Nothing goes to Asta.

### Install

```bash
command -v auto-discovery || uv tool install --python 3.13 asta-autodiscovery
auto-discovery --version
auto-discovery --help        # the source of truth for flags; it can differ from the remote service
```

Keep `--python 3.13`: on a newer Python, one dependency (`h5py`) has no prebuilt package and the install fails partway through. If the command isn't found after installing, run `uv tool update-shell` or open a new shell.

### Keys and models

Pass `--model <provider>/<model>` (or set `AUTODISCOVERY_MODEL`); the belief and vision models fall back to it. With both keys, use OpenAI unless the person asks otherwise. Our preferences:

| Key | Model | Per experiment |
|---|---|---|
| `OPENAI_API_KEY` | `openai/gpt-6-luna` | about $0.01 and 1 to 2 minutes of wall time on a small table (two run at once); up to $0.10 and 6 to 8 minutes on bigger data |
| `ANTHROPIC_API_KEY` | `anthropic/claude-opus-5` | about 10 to 15 minutes and $2 |

`--dedupe` needs an embedding model (`--embedding_model openai/text-embedding-3-large`), so with only an Anthropic key leave it off. For Gemini, the person makes a Google Cloud service-account key and sets `GOOGLE_APPLICATION_CREDENTIALS`, `VERTEXAI_PROJECT` and `VERTEXAI_LOCATION=global`.

Ask the person how you should reach their key, and use only what they tell you. Never ask for the key itself in chat, because it would stay in the transcript. The person sets it in their shell.

### A run

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

### The next round

Seeds only take on a new run, so each round is a new run, seeded with the picks. Write them to a JSON list of `{"hypothesis", "experiment_plan"}` copied verbatim from their nodes, and add `--warmstart_experiments <file> --n_warmstart <count>` to a fresh `--out_dir`. The seeds run first, as the first children of `node_1_0`, but not in the file's order, so match them by hypothesis.

Growing one run, without seeds, also works, but only this way:

```bash
cp -Rp <run> <run>-backup
mkdir <run>-flat && find <run> -maxdepth 1 -type f ! -name args.json -exec cp -p {} <run>-flat/ \;
<the same command> --continue_from_dir <run>-flat --out_dir <run> --n_experiments <existing + k + 1>
```

Pointing `--continue_from_dir` at the run's own folder fails after it has overwritten `args.json`, and pointing it at the untouched folder fails on `rich_outputs/`. On a resume, `--n_experiments` is the new total, counting the data-loading node, so add 1. The usage log is overwritten, so add up its cost first. Seeds given here are silently ignored.

### Watch the first minute

- **Check that the files appear.** `mcts_node_1_0.json` comes within about a minute, and the first experiment 2 to 4 minutes after. A bad key ends the run in under a second with no experiments, and the report still says SUCCEEDED. The log has `AuthenticationError`.
- **If a safety filter cuts a response off,** AutoDS records nothing and can end at once, with exit status 0 and "No new experiment generated". Search the log for `content_filter`. We've seen it with `anthropic/claude-opus-5-5` on infectious-disease data, where `anthropic/claude-opus-5` ran the same data to the end.
- **Tracebacks in the log** are usually from the generated code, which the agents fix. Ignore them unless an experiment fails. If several fail the same way, say so rather than letting the budget drain.

## With the library

You pay for it, through your coding agent. You are the model: you write the hypothesis, give your prior, write and run the code, and judge the result. The library gives you the node type, the belief maths and the surprise rule, so the files come out the same as a CLI run's. Nothing here calls a model, and you need no key.

Source: [allenai/asta-autodiscovery](https://github.com/allenai/asta-autodiscovery) ([mcts.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/mcts.py), [beliefs.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/beliefs.py), [mcts_utils.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/mcts_utils.py)).

```bash
uv venv --python 3.13 && uv pip install asta-autodiscovery    # needs 3.13 or later
```

Run the code below with `.venv/bin/python`. Keep the run in git (`git init` if the folder isn't a repo yet), so the prior is committed before the code.

You set the priors, so profile the data without grouping it by anything the prompt asks about: don't look at the answers first.

### One experiment

```python
import os

from autodiscovery.beliefs import BeliefTrueFalseCat as B
from autodiscovery.mcts import MCTSNode
from autodiscovery.mcts_utils import (
    get_query_from_experiment,
    get_self_value,
    load_mcts_from_json,
    save_mcts_node,
)

OUT = "autods"  # the run's folder of mcts_node_*.json
os.makedirs(OUT, exist_ok=True)  # save_mcts_node writes into it, and doesn't create it


def node_for(exp, parent, level, idx):
    return MCTSNode(
        level=level,
        node_idx=idx,
        hypothesis=exp["hypothesis"],
        experiment_plan=exp["experiment_plan"],
        query=get_query_from_experiment(exp),
        parent=parent,
    )


# Once per run: node_1_0 loads the data. No hypothesis, no beliefs.
load = {
    "hypothesis": None,
    "experiment_plan": {
        "objective": "Load the data and summarise it.",
        "steps": "...",
        "deliverables": "...",
    },
}
n1 = node_for(load, MCTSNode(level=0, node_idx=0), 1, 0)
n1.code, n1.code_output, n1.analysis, n1.success = (
    "...",
    "...",
    "344 rows, 7 columns.",
    True,
)
save_mcts_node(n1, OUT)

# Each experiment.
MCTSNode._creation_counter = 0  # the loader asserts on this counter
root, by_level = load_mcts_from_json(OUT)
parent = by_level[1][0]
exp = {
    "hypothesis": "...",
    "experiment_plan": {"objective": "...", "steps": "...", "deliverables": "..."},
}
level = parent.level + 1
node = node_for(exp, parent, level, len(by_level.get(level, [])))

node.prior = B.DistributionFormat(
    5, 0, 1, 1, 2, 1
)  # n, definitely true, maybe true, uncertain, maybe false, definitely false
node.prior.get_mean_belief()
save_mcts_node(node, OUT)  # commit this file before writing any code

node.code, node.code_output, node.analysis, node.review, node.success = (
    "...",
    "...",
    "...",
    "...",
    True,
)

w = 2  # the CLI's evidence weight
node.posterior = B.DistributionFormat(
    5 * w, 0, 0, 0, 1 * w, 4 * w, prior_params=node.prior.get_params()
)
node.posterior.get_mean_belief()
node.belief_change = abs(node.posterior.mean - node.prior.mean)
node.kl_divergence = B.kl_divergence(node.posterior, node.prior)
node.self_value, node.surprising = get_self_value(
    node.belief_change,
    node.kl_divergence,
    binary=False,
    width=0.2,
    kl_scale=5.0,
    mode="belief",
)
from autodiscovery.run import (
    _theoretical_max_boolean_cat,
)  # no model call; the report shows this as the surprise

node.normalized_surprisal = (
    node.posterior.mean - node.prior.mean
) / _theoretical_max_boolean_cat(5, w, prior_params=node.prior.prior_params)
node.update_counts(visits=1, reward=node.self_value)
save_mcts_node(node, OUT, to_root=True)
```

### The rules

- **Your belief, sampled five times.** For the prior, judge from what you know of the field, five times from different angles, and count the answers into the five categories. For the posterior, set the prior aside and judge only the plan, the analysis and the review, five times again. "Can't say" (no judgement at all) drops out of n; "uncertain" is a category and counts. Keep your reasons beside the node.
- **The prior is on disk, and committed, before any code is written.** Then the posterior. That's what makes the surprise honest.
- **Pass the arguments above.** The posterior's counts are doubled and sit on the prior (`prior_params`), and `get_self_value` takes the CLI's settings. With the defaults, nothing comes out surprising.
- **Names:** `node_<level>_<n>`. The first hypothesis is at level 2, a child is its parent's level + 1, and n counts across the whole level, not per parent.
- **Choosing what's next is yours.** A real run picks the parent with its selection policy; following the surprise by hand is a choice, so say so in the run's README.
- **Never call** anything that takes a model: `beliefs.get_belief`, `calculate_prior_and_posterior_beliefs`, `MCTSNode.get_next_experiment`, `deduplication.dedupe`, `agents.get_agents`, `run.main`. `save_nodes(..., model=None, embedding_model=None, run_dedupe=False)` is safe.

### Reading it back

`load_mcts_from_json(OUT)` gives the tree, `nodes_to_csv(OUT, "nodes.csv")` (from `autodiscovery.nodes_to_csv`) the table, and `autodiscovery.report.generate_report(OUT)` an HTML report (it reads the settings from an `args.json` in the folder, if there is one). Keep the prompt and the data description in the run folder too, as `description.md`. Set `MCTSNode._creation_counter = 0` before each load in the same process.
