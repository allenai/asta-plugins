"""Write each run's experiments table and figures from its saved record.

    python3 scripts/runlog.py

For each run under .asta/autodiscovery/<run>/, reads
  results.json    from the hosted service (`asta autodiscovery results <run_id> -o ...`), or
  local/          the local CLI's --out_dir: mcts_node_*.json and rich_outputs/
and writes
  runs/<run>/experiments.csv           the columns of the web app's download, then Decision, Reason and Reviewer
  .asta/autodiscovery/<run>/figures/   the experiments' figures, for review before use
A run whose experiments.csv already exists is left alone: a finished run does not change, and the review is
kept there. Stops before writing anything if any experiment text looks like row-level data.
"""

import base64
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The web app's download of a run, so a download and this file are interchangeable.
COLS = (
    "ID",
    "Hypothesis",
    "Surprisal",
    "Belief Before",
    "Belief After",
    "Direction",
    "Findings",
)
COLS += ("Validity Check", "Objective", "Steps", "Deliverables")
TEXT = (
    "Hypothesis",
    "Findings",
    "Validity Check",
    "Objective",
    "Steps",
    "Deliverables",
)
REVIEW = ("Decision", "Reason", "Reviewer")
ROW_LEVEL = re.compile(
    r"\b(caseid|hhid|\w+_id)\s*[=:]\s*\d+|\b(row|index|record)\s*#?\s*\d{2,}\b|\bdf\.(loc|iloc)\[",
    re.I,
)


def belief(p):
    """The web app's label for a belief: below 0.25, below 0.5, exactly 0.5, below 0.75, or above."""
    p = round(p, 6)
    if p < 0.25:
        return "Likely False"
    if p < 0.5:
        return "Maybe False"
    if p == 0.5:
        return "Uncertain"
    return "Maybe True" if p < 0.75 else "Likely True"


def local_experiments(d):
    """Read the local CLI's output directory into the hosted results' experiment shape."""
    out = []
    for f in sorted(d.glob("mcts_node_*.json")):
        n = json.loads(f.read_text())
        if int(n["id"].split("_")[1]) < 2 or not n.get("hypothesis"):
            continue  # the root and the seed level hold no experiment
        ro = d / "rich_outputs" / f"ro_{n['id'][5:]}.json"
        out.append(
            {
                "id_in_run": n.get("creation_idx"),
                "experiment_id": n["id"],
                "hypothesis": n["hypothesis"],
                "analysis": n.get("analysis") or "",
                "review": n.get("review") or "",
                "experiment_plan": n.get("experiment_plan") or {},
                "prior": (n.get("prior") or {}).get("mean"),
                "posterior": (n.get("posterior") or {}).get("mean"),
                "surprise": n.get("normalized_surprisal"),
                "rich_outputs": json.loads(ro.read_text()) if ro.exists() else [],
            }
        )
    return out


def main():
    tables = {}
    for raw in sorted(
        p for p in (ROOT / ".asta/autodiscovery").glob("*") if p.is_dir()
    ):
        out = ROOT / "runs" / raw.name / "experiments.csv"
        if out.exists():
            continue
        if (raw / "results.json").exists():
            exps = json.loads((raw / "results.json").read_text())["experiments"]
        elif (raw / "local").exists():
            exps = local_experiments(raw / "local")
        else:
            continue
        counts = {}
        for e in exps:
            counts[e["id_in_run"]] = counts.get(e["id_in_run"], 0) + 1
        (raw / "figures").mkdir(exist_ok=True)
        rows = []
        # In ID order, as the download is; a repeated ID keeps the order of the saved results.
        for e in sorted(exps, key=lambda e: e["id_in_run"]):
            n, plan, surprise = (
                e["id_in_run"],
                e.get("experiment_plan") or {},
                e.get("surprise") or 0,
            )
            for i, ro in enumerate(e.get("rich_outputs") or []):
                # each output carries the same figure as JPEG, PNG and SVG; keep the JPEG
                if isinstance(ro, dict) and "image/jpeg" in ro:
                    name = (
                        f"{n}-{e['experiment_id']}-{i}.jpg"
                        if counts[n] > 1
                        else f"{n}-{i}.jpg"
                    )
                    (raw / "figures" / name).write_bytes(
                        base64.b64decode(ro["image/jpeg"])
                    )
            values = (
                n,
                e["hypothesis"],
                f"{abs(surprise):.3f}",
                belief(e["prior"]),
                belief(e["posterior"]),
                "Positive" if surprise > 0 else "Negative",
                e.get("analysis") or "",
                e.get("review") or "",
                plan.get("objective") or "",
                plan.get("steps") or "",
                plan.get("deliverables") or "",
            )
            rows.append({**dict(zip(COLS, values)), **dict.fromkeys(REVIEW, "")})
        tables[out] = rows
    hits = [
        (out.parent.name, x["ID"], m.group(0))
        for out, rows in tables.items()
        for x in rows
        for f in TEXT
        for m in ROW_LEVEL.finditer(x[f])
    ]
    if hits:
        sys.exit(
            "row-level data in the experiment text, nothing written:\n"
            + "\n".join(f"  {r}-{n}: {t!r}" for r, n, t in hits)
        )
    for out, rows in tables.items():
        out.parent.mkdir(parents=True, exist_ok=True)
        # With a byte-order mark, as the download has, so Excel reads it as UTF-8.
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"{out.relative_to(ROOT)}: {len(rows)} experiments")


if __name__ == "__main__":
    main()
