# AutoDiscovery exploration

Three ways to explore a dataset with AutoDS. Pick one with the person.

| Option | What you do | How |
|---|---|---|
| AutoDS on its own | Run AutoDS, seed the next round with what surprised it, and keep extending or forking the run until a round brings nothing new | the `autodiscovery` skill's "The loop" |
| Theories first | Generate theories from the literature, then seed AutoDS with their predictions | [Gap-Driven Theory Testing](../gap-driven-theory-testing/README.md) |
| Experiments first | Run AutoDS, then generate theories that have to explain what it found | [Data Driven Theory Generation](../data-driven-theory-generation/README.md) |

How to describe the data and write the prompt is in the `autodiscovery` skill.
