# <Title, the same as the write-up's>

An AutoDiscovery exploration of <the dataset>, by <who>, published as one Quarto site.

## What was asked

<The researcher's question in a paragraph; the message as sent and the sub-questions are in [questions.md](questions.md).>

## How it came out

<A paragraph: the runs, what came back, what could not be answered, the next step. The write-up, `index.qmd`, has every number linked to the experiment it came from.>

## Layout

| Path | What it holds |
|---|---|
| `index.qmd` | The write-up |
| `data.qmd` | The data page: the description each run received |
| `runs/*.qmd` | One page per run, with its prompt and experiments |
| `questions.md` | The researcher's message and the sub-questions |
| `prompts/` | The prompt each run received |
| `descriptions/` | The data descriptions each run received |
| `autodiscovery/` | `runs.csv` (the run log) and `experiments.csv` (the ranked list); raw records per run stay local |
| `evidence.yml` | Verbatim quotes behind the write-up's numbers, checked by `scripts/check.py` |
| `figures/` | The figures used on the page, each reviewed before use |
| `scripts/` | Extraction, descriptions, the run log, the run pages and the checks |
| `project.md`, `work/` | The plan and one folder per workflow step |

Build and preview with `make check` and `make preview`. Restricted data never enters git: `data/` and AutoDiscovery's raw records are ignored.
