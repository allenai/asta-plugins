# Library: do it in the coding agent

You pay for it, through your coding agent's plan. You do the model's part yourself: read the papers, pull out the findings, write the theories, and judge the experiments. The open-source libraries give you the types, the ids and the outputs, so the run's files are the same as a CLI run's.

```bash
uv venv && uv pip install asta-theorizer "pymupdf4llm<2" asta-autodiscovery
```

Use the libraries for their types and bookkeeping, and never call a function that takes a `model_str`, because those call a model.

**Theorizer:** [allenai/asta-theorizer](https://github.com/allenai/asta-theorizer). Run `theorize guide` and follow its Workflow 5.
- The shapes: `theorize guide --schema record` and `--schema theory` (also `paper`, `schema_slot`).
- Papers: `theorize papers fetch`, or `theorize papers import --no-metadata` for the person's own.
- Your records: `th.add_records(paper_id, records, extraction_schema=schema)` gives each one the uuid its laws cite.
- Your theories: `th.add_theories(theories, query, extraction_schema=schema)` refuses any citation that doesn't resolve.
- Output: `theorize export html`.

**AutoDS:** [allenai/asta-autodiscovery](https://github.com/allenai/asta-autodiscovery).
- Each experiment is an `MCTSNode` ([mcts.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/mcts.py)), saved with `to_dict()` as `mcts_node_<depth>_<n>.json`, which the site draws.
- The prior and the posterior are each a `BeliefTrueFalseCat.DistributionFormat` ([beliefs.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/beliefs.py)), made from your counts of definitely true, maybe true, uncertain, maybe false and definitely false. The posterior's mean is `posterior.get_mean_belief(prior=prior)`.
- Whether it's surprising: `get_self_value(belief_change, kl_divergence)` ([mcts_utils.py](https://github.com/allenai/asta-autodiscovery/blob/main/packages/autodiscovery/src/autodiscovery/mcts_utils.py)), with `BeliefTrueFalseCat.kl_divergence(posterior, prior)`, as a real run does.
- Write the prior and commit it to git before you write any code. Then run the code, write the posterior, and commit again.
