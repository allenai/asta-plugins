---
name: hypothesis_driven_research
description: |
  Literature-grounded hypothesis generation. Survey the literature, raise a
  hypothesis per gap, test each, and write a closing report.
---

# Hypothesis-driven research

Survey the literature, raise a hypothesis for each gap, test each one, and write a closing report.

## Flow

```mermaid
flowchart TD
  start([start])
  scope["Scope"]
  start --> scope
  definitions["Definitions"]
  scope --> definitions
  lit_review["Literature review"]
  definitions --> lit_review
  subgraph sub1["for each gap"]
    direction TB
    hypothesis["Hypothesis"]
    experiment_design["Experiment design"]
    evidence_gathering["Evidence gathering"]
    analysis["Analysis"]
    hypothesis --> experiment_design --> evidence_gathering --> analysis
  end
  lit_review --> hypothesis
  closing["Closing synthesis"]
  analysis --> closing
  closing --> stop([stop])
```

## Nodes

| id | type | inputs | description | skills |
|---|---|---|---|---|
| `scope` | `scope` | — | One line: the question under study. | — |
| `definitions` | `definitions` | `scope` | Pin down each term so it's testable against data. | — |
| `lit_review` | `literature_review` | `scope, definitions` | Survey the literature with `asta literature interactive`. Emit `gaps[]` — one hypothesis per gap. | `asta-preview:find-literature` |
| `hypothesis` | `hypothesis` | `lit_review` | For each gap: turn it into a falsifiable hypothesis with a concrete prediction. | — |
| `experiment_design` | `experiment_design` | `hypothesis` | Design an experiment that could falsify the hypothesis. | — |
| `evidence_gathering` | `evidence_gathering` | `experiment_design` | Locate the data the design needs; note anything that diverged from it. | — |
| `analysis` | `analysis` | `hypothesis, experiment_design, evidence_gathering` | Get the verdict from DataVoyager (`asta analyze-data submit`), framed on the hypothesis with the gathered data. It must come from a run on real data, not your own reasoning. | `asta-preview:analyze-data` |
| `closing` | `synthesis` | `analysis` (all hypotheses) | Reconcile the verdicts into one answer to the question. | — |

The `hypothesis` tasks are filled and closed at creation from the literature gaps — see plan.md.
