# AutoDiscovery exploration

You bring a dataset and what you're curious about. AutoDS runs 50 experiments on it. We look at what surprised it, false-to-true shifts first, and seed the next 50 with those. That repeats until a round brings nothing new. Alongside, if you want, we search the literature or build theories, so they're ready when the next round comes back. The front page says what came back, including what came back empty, with every number linked to its experiment.

How to describe the data, write the prompt and run the loop is in the `autodiscovery` skill.

## Plan

| Step | What it does | Configuration |
|---|---|---|
| 1. Look at the data | What the files hold, how they were collected (weights, clusters, strata, arms), and what the question needs that isn't there | the data the person names |
| 2. First round | AutoDS on their question and an objective description of the data | 50 experiments, about $1 hosted |
| Alongside (optional) | A literature search on the question, ready by the check-in | |
| Check-in | The round's surprising shifts, and what's next: another round seeded with them, a literature search, or theories | after every round, unless they say to keep going |
| 3. More rounds | 50 at a time, seeded with the top shifts, until a round brings no new surprising shift | the person's budget, if they set one |
| 4. Front page | What came back, including null results | |

> You can change:
>
> - **Budget:** a total for the whole loop; by default it runs until a round finds nothing new.
> - **Literature:** a search alongside the first round, or none.
> - **Check-ins:** after every round, or keep going to the end.

## Steps

1. **Look at the data** before proposing anything, and say what the question would need that the data doesn't have.
2. **First round.** Describe the data and write the prompt from their question, then start 50 experiments. If they wanted the literature, start the search at the same time.
3. **Check in.** Show the round's surprising experiments in the skill's order, in their own words, with the artifacts marked. Offer the next step:
   - **another round**, seeded with the top shifts;
   - **a literature search** on what came back;
   - **theories** that explain it ([Data Driven Theory Generation](../data-driven-theory-generation/README.md)'s step 4).

   Then go again. When a round brings no new surprising shift, or the budget runs out, say so and stop.
4. **Front page:** the workspace's cover. Findings are led by the experiments that found them, in their own words, each number linked to its experiment, with how far to trust it. Null results say what was tested and came back with nothing, and what the data couldn't test. Next steps say what's worth following up, such as a [secondary reproduction](../secondary-reproduction/README.md) on independent data.
