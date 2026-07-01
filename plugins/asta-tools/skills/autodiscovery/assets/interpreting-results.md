## Interpreting Results

The outcome of an auto-discovery run is a set of experiment (node) descriptions: the hypothesis, generated code, and outcome.
These are in machine-readable form and need summarization for the user. Note the following definitions:

- **Surprise**: A normalized surprisal score. Higher = more surprising relative to the prior belief.
- **Prior/Posterior**: Mean of the prior and posterior belief distributions. A large shift indicates the experiment changed the model's beliefs significantly.
- **is_surprising**: Boolean flag set when surprise exceeds the configured threshold.

## Presenting Results

When showing results to the user:
2. Inspect the structured output for summarization
3. Present results in a clean, readable format
4. Give some high-level statistics (attempted/failed runs)
3. Summarize a few of the most surprising experiments
4. Offer to drill deeper into specific runs or experiments

When showing experiment details, focus on the hypothesis, analysis, and review fields. Show code and code_output only if specifically asked.

