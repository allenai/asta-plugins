# [Title, the same as the write-up's]

An AutoDiscovery exploration of [the dataset], by [who], published as one Quarto site.

## Mission

[The mission in a paragraph; the goal, the data and the constraints are in [mission.md](mission.md).]

## How it came out

[A paragraph: the runs, what came back, what could not be answered, the next step. The write-up, `index.qmd`, has every number linked to the experiment it came from.]

## Layout

| Path | What it holds |
|---|---|
| `mission.md` | The goal, the data and the constraints |
| `index.qmd` | The write-up |
| `runs/<run>/run.md` | The configuration the run was submitted with: prompt, data description, files, experiments, link |
| `runs/<run>/experiments.csv` | The run's experiments: the web app's download, with the review's Next step, Human review and Agent review after ID |
| `.asta/autodiscovery/<run>/` | The run's full record as saved, and its figures |
| `evidence.yml` | Verbatim quotes behind the write-up's numbers, each copied from a run's `experiments.csv` |
| `figures/` | The figures used on the page, each reviewed before use |
| `scripts/` | The extraction script, and `runlog.py`, which writes each run's `experiments.csv` |

Build and preview with `make check` and `make preview`. The source data and the extract never enter git: `data/` is ignored.
