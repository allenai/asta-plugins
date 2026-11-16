"""Write the run pages, the write-up's runs table and the sidebar from the run log.

    python3 scripts/build_pages.py

Reads autodiscovery/runs.csv and each run's index.json and prompt file. Writes
  runs/<run>.qmd              Prompt, Run, Experiments; links to the previous and next run and the write-up
  _generated/runs-table.md    the table the write-up includes: prompt as submitted, experiments, run page, hosted run
  _generated/sidebar.yml      Write-up, Data, and the run pages under their round
Rows are ordered with rises in belief first, then falls, each largest change first.
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cell = lambda s: " ".join(str(s).split()).replace("|", "\\|")  # noqa: E731


def main():
    rows = [
        r for r in csv.DictReader(open(ROOT / "autodiscovery/runs.csv")) if r["run_id"]
    ]
    (ROOT / "runs").mkdir(exist_ok=True)
    (ROOT / "_generated").mkdir(exist_ok=True)
    table = ["| Prompt | Experiments | Run | AutoDiscovery |", "|---|---|---|---|"]
    rounds = {}
    for i, r in enumerate(rows):
        index = json.loads(
            (ROOT / "autodiscovery" / r["run"] / "index.json").read_text()
        )["experiments"]
        prompt = (ROOT / r["prompt"]).read_text().strip().split("\n\n")
        ordered = sorted(
            index,
            key=lambda e: (
                e["posterior"] < e["prior"],
                -abs(e["posterior"] - e["prior"]),
            ),
        )
        nav = []
        if i > 0:
            nav.append(f"[← Run {rows[i - 1]['label']}]({rows[i - 1]['run']}.qmd)")
        if i < len(rows) - 1:
            nav.append(f"[Run {rows[i + 1]['label']} →]({rows[i + 1]['run']}.qmd)")
        nav.append("[Back to the write-up](../index.qmd)")
        exp = [
            "| Experiment | Hypothesis | Belief before → after | Surprising |",
            "|---|---|---|---|",
        ]
        for e in ordered:
            label = f"{r['label']}-{e['experiment']}" + (
                " ¹" if e.get("duplicate_number") else ""
            )
            shown = (
                f'[{label}]({e["link"]}){{target="_blank"}}' if e.get("link") else label
            )
            exp.append(
                f"| {shown} | {cell(e['hypothesis'])} | {e['prior']:.2f} → {e['posterior']:.2f} | {'yes' if e['surprising'] else 'no'} |"
            )
        note = (
            "\n¹ The service gave two experiments this number; the link opens one of them.\n"
            if any(e.get("duplicate_number") for e in index)
            else ""
        )
        settings = (
            ", ".join(
                f"{k.replace('_', ' ')} {r[k]}"
                for k in ("exploration_weight", "surprisal_width", "evidence_weight")
                if r.get(k)
            )
            or "service defaults"
        )
        quoted = "\n>\n".join("> " + p for p in prompt)
        page = f"""---
title: "Run {r["label"]}: {r["title"]}"
toc: false
---

{" · ".join(nav)}

## Prompt

The prompt as submitted:

{quoted}

## Run

| | |
|---|---|
| File | `{r["files"]}` ([description](../data.qmd)) |
| Experiments | {r["n_experiments"]} requested, {len(index)} finished |
| Search settings | {settings} |
| Run | {"[open in AutoDiscovery](" + r["shared_url"] + '){target="_blank"}' if r["shared_url"] else "run locally with the asta-autodiscovery CLI"} |

## Experiments

Each row is one experiment: the hypothesis AutoDiscovery wrote, its belief that the hypothesis is true before and after running the analysis (0 to 1), and whether the service flagged the change as surprising. Rows where belief rose come first, then rows where it fell, each ordered by the size of the change. Where the run was hosted, the experiment link opens its code, output and figures.

{chr(10).join(exp)}
{note}"""
        (ROOT / "runs" / f"{r['run']}.qmd").write_text(page)
        hosted = (
            f'[open]({r["shared_url"]}){{target="_blank"}}'
            if r["shared_url"]
            else "local"
        )
        table.append(
            f"| {cell(prompt[0])} | {len(index)} | [Run {r['label']}](runs/{r['run']}.qmd) | {hosted} |"
        )
        rounds.setdefault(r["round"], []).append(r["run"])
        print(f"runs/{r['run']}.qmd: {len(index)} experiments")
    if len(rounds) > 1:
        table = [
            "| Round | Prompt | Experiments | Run | AutoDiscovery |",
            "|---|---|---|---|---|",
        ] + [f"| {r['round']} " + line[1:] for r, line in zip(rows, table[2:])]
    (ROOT / "_generated/runs-table.md").write_text("\n".join(table) + "\n")
    side = [
        "website:",
        "  sidebar:",
        "    contents:",
        '      - text: "Write-up"',
        "        href: index.qmd",
        '      - text: "Data"',
        "        href: data.qmd",
        '      - section: "Runs"',
        "        contents:",
    ]
    for rd, runs in rounds.items():
        side.append(f'          - section: "Round {rd}"')
        side.append("            contents:")
        side += [f"              - runs/{run}.qmd" for run in runs]
    (ROOT / "_generated/sidebar.yml").write_text("\n".join(side) + "\n")
    print("wrote _generated/runs-table.md and _generated/sidebar.yml")


if __name__ == "__main__":
    main()
