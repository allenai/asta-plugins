# AutoDS with the library

You pay for it, through your coding agent. You are the model: you write the hypothesis, give your prior, write and run the code, and judge the result. The library gives you the node type, the belief maths and the surprise rule, so the files come out the same as a CLI run's. Nothing here calls a model, and you need no key.

Source: [allenai/asta-autodiscovery](https://github.com/allenai/asta-autodiscovery) ([mcts.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/mcts.py), [beliefs.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/beliefs.py), [mcts_utils.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/mcts_utils.py)).

```bash
uv venv --python 3.13 && uv pip install asta-autodiscovery    # needs 3.13 or later
```

## One experiment

```python
from autodiscovery.beliefs import BeliefTrueFalseCat as B
from autodiscovery.mcts import MCTSNode
from autodiscovery.mcts_utils import (
    get_query_from_experiment,
    get_self_value,
    load_mcts_from_json,
    save_mcts_node,
)

OUT = "autods"  # the run's folder of mcts_node_*.json


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
node.update_counts(visits=1, reward=node.self_value)
save_mcts_node(node, OUT, to_root=True)
```

## The rules

- **Your belief, sampled five times.** For the prior, judge from what you know of the field, five times from different angles, and count the answers into the five categories. For the posterior, set the prior aside and judge only the plan, the analysis and the review, five times again. "Can't say" drops out of n. Keep your reasons beside the node.
- **The prior is on disk, and committed, before any code is written.** Then the posterior. That's what makes the surprise honest.
- **Pass the arguments above.** The posterior's counts are doubled and sit on the prior (`prior_params`), and `get_self_value` takes the CLI's settings. With the defaults, nothing comes out surprising.
- **Names:** `node_<level>_<n>`. The first hypothesis is at level 2, a child is its parent's level + 1, and n counts across the whole level, not per parent.
- **Choosing what's next is yours.** A real run picks the parent with its selection policy; following the surprise by hand is a choice, so say so in the run's README.
- **Never call** anything that takes a model: `beliefs.get_belief`, `calculate_prior_and_posterior_beliefs`, `MCTSNode.get_next_experiment`, `deduplication.dedupe`, `agents.get_agents`, `run.main`. `save_nodes(..., model=None, embedding_model=None, run_dedupe=False)` is safe.

## Reading it back

`load_mcts_from_json(OUT)` gives the tree, `nodes_to_csv(OUT, "nodes.csv")` the table, and `autodiscovery.report.generate_report(OUT)` an HTML report (it reads the settings from an `args.json` in the folder, if there is one). Set `MCTSNode._creation_counter = 0` before each load in the same process.
