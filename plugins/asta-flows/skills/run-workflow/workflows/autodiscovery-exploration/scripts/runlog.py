"""Write the run log, the experiments table and a per-run index from each run's saved results.

    python3 scripts/runlog.py

Reads autodiscovery/runs.csv (run, round, label, title, run_id, prompt, sub_questions, files and
n_experiments filled in by hand; run_id after `asta autodiscovery create`, or "local" for a run of the
local CLI) and each run's full record under .asta/autodiscovery/<run>/, either
  results.json    from the hosted service (`asta autodiscovery results <run_id> -o ...`)
  local/          the local CLI's --out_dir: mcts_node_*.json, rich_outputs/, args.json
Writes:
  autodiscovery/runs.csv            status, settings, extract hash and shared link filled in
  autodiscovery/experiments.csv     a Run column, then the web app's download columns, in ID order; every
                                    column it does not write (the review's, and any a team adds) is kept
  autodiscovery/<run>/index.json    per-experiment text the pages quote (no code, output or ids)
  .asta/autodiscovery/<run>/figures/   the experiments' figures, for review before use
Stops before writing anything if any experiment text looks like row-level data.
"""

import base64
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AD = ROOT / "autodiscovery"
RAW = ROOT / ".asta" / "autodiscovery"
# The review is filled in by hand: Decision (follow-up analysis, small validation, none or methods issue),
# Reason and Reviewer.
REVIEW = ("Decision", "Reason", "Reviewer")
# The columns runlog.py writes in experiments.csv; every other column is kept as the team left it.
# After Run, they are the web app's download (one file per run), so a download can be pasted in as it is.
GENERATED = (
    "Run",
    "ID",
    "Hypothesis",
    "Surprisal",
    "Belief Before",
    "Belief After",
    "Direction",
    "Findings",
    "Validity Check",
    "Objective",
    "Steps",
    "Deliverables",
)
TEXT = (
    "Hypothesis",
    "Findings",
    "Validity Check",
    "Objective",
    "Steps",
    "Deliverables",
)
SHARED = "https://autodiscovery.allen.ai/runs/shared/{run_id}"
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


def local_results(d):
    """Read the local CLI's output directory into the hosted results shape."""
    nodes = []
    for f in sorted(d.glob("mcts_node_*.json")):
        n = json.loads(f.read_text())
        level = int(n["id"].split("_")[1])
        if level < 2 or not n.get("hypothesis"):
            continue  # the root and the seed level hold no experiment
        ro = d / "rich_outputs" / f"ro_{n['id'][5:]}.json"
        nodes.append(
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
                "is_surprising": bool(n.get("surprising")),
                "rich_outputs": json.loads(ro.read_text()) if ro.exists() else [],
            }
        )
    args = (
        json.loads((d / "args.json").read_text()) if (d / "args.json").exists() else {}
    )
    meta = {
        k: args[k]
        for k in ("exploration_weight", "surprisal_width", "evidence_weight")
        if k in args
    }
    return {"run": {"status": "FINISHED", "metadata": meta}, "experiments": nodes}


def main():
    rows = list(csv.DictReader(open(AD / "runs.csv")))
    # Keyed by run, experiment and hypothesis: the service can repeat an experiment number within a run.
    kept, extra = {}, list(REVIEW)
    if (AD / "experiments.csv").exists():
        with open(AD / "experiments.csv", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            extra = [c for c in reader.fieldnames if c not in GENERATED]
            extra += [c for c in REVIEW if c not in extra]
            for x in reader:
                kept[(x["Run"], x["ID"], x["Hypothesis"])] = {
                    k: x.get(k) or "" for k in extra
                }
    table, indexes = [], {}
    for r in rows:
        if not r["run_id"]:
            continue
        local = r["run_id"] == "local"
        raw = RAW / r["run"]
        if local:
            out = next(
                (raw / n for n in ("local", "raw") if (raw / n).exists()),
                raw / "local",
            )
            d = local_results(out)
        else:
            d = json.loads((raw / "results.json").read_text())
        run, meta = d["run"], d["run"].get("metadata") or {}
        meta = meta.get("metadata", meta)
        r["status"] = run.get("status", r["status"])
        r["shared_url"] = "" if local else SHARED.format(run_id=r["run_id"])
        for k in ("exploration_weight", "surprisal_width", "evidence_weight"):
            r[k] = meta.get(k, r.get(k, ""))
        first = ROOT / "data" / r["files"].split()[0]
        if first.exists() and not r["extract_hash"]:
            r["extract_hash"] = hashlib.sha256(first.read_bytes()).hexdigest()
        counts = {}
        for e in d["experiments"]:
            counts[e["id_in_run"]] = counts.get(e["id_in_run"], 0) + 1
        figdir = raw / "figures"
        figdir.mkdir(exist_ok=True)
        index, mine = [], []
        for e in d["experiments"]:
            n = e["id_in_run"]
            link = (r["shared_url"] + f"?exp={n}") if r["shared_url"] else ""
            figs = []
            for i, ro in enumerate(e.get("rich_outputs") or []):
                if isinstance(ro, dict) and "image/jpeg" in ro:
                    p = figdir / f"{n}-{i}.jpg"
                    p.write_bytes(base64.b64decode(ro["image/jpeg"]))
                    figs.append(p.name)
            plan = e.get("experiment_plan") or {}
            surprise = e.get("surprise") or 0
            mine.append(
                {
                    "Run": r["run"],
                    "ID": n,
                    "Hypothesis": e["hypothesis"],
                    "Surprisal": f"{abs(surprise):.3f}",
                    "Belief Before": belief(e["prior"]),
                    "Belief After": belief(e["posterior"]),
                    "Direction": "Positive" if surprise > 0 else "Negative",
                    "Findings": e.get("analysis") or "",
                    "Validity Check": e.get("review") or "",
                    "Objective": plan.get("objective") or "",
                    "Steps": plan.get("steps") or "",
                    "Deliverables": plan.get("deliverables") or "",
                    **kept.get(
                        (r["run"], str(n), e["hypothesis"]), dict.fromkeys(extra, "")
                    ),
                }
            )
            index.append(
                {
                    "experiment": n,
                    "node": e["experiment_id"],
                    "hypothesis": e["hypothesis"],
                    "prior": e["prior"],
                    "posterior": e["posterior"],
                    "surprise": e.get("surprise"),
                    "plan": (e.get("experiment_plan") or {}).get("objective", "")
                    if local
                    else "",
                    "surprising": bool(e.get("is_surprising")),
                    "analysis": e.get("analysis") or "",
                    "review": e.get("review") or "",
                    "figures": figs,
                    "link": link,
                    "duplicate_number": counts[n] > 1,
                }
            )
        table += sorted(mine, key=lambda x: x["ID"])  # ID order, as the download is
        indexes[r["run"]] = {
            "run": r["run"],
            "run_id": r["run_id"],
            "experiments": index,
        }
        print(f"{r['run']}: {r['status']}, {len(index)} experiments")
    hits = [
        (x["Run"], x["ID"], m.group(0))
        for x in table
        for f in TEXT
        for m in ROW_LEVEL.finditer(x[f])
    ]
    if hits:
        sys.exit(
            "row-level data in the experiment text, nothing written:\n"
            + "\n".join(f"  {r}-{n}: {t!r}" for r, n, t in hits)
        )
    for run, index in indexes.items():
        (AD / run).mkdir(exist_ok=True)
        (AD / run / "index.json").write_text(
            json.dumps(index, indent=1, ensure_ascii=False) + "\n"
        )
    with open(AD / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    if table:
        # With a byte-order mark, as the download has, so Excel reads it as UTF-8.
        with open(AD / "experiments.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(table[0]))
            w.writeheader()
            w.writerows(table)
    print(f"{len(indexes)} runs, {len(table)} experiments")


if __name__ == "__main__":
    main()
