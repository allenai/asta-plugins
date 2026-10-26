"""Write the run log, the ranked list and a per-run index from each run's saved results.

    python3 scripts/runlog.py

Reads autodiscovery/runs.csv (run, round, label, title, run_id, prompt, sub_questions, files and
n_experiments filled in by hand; run_id after `asta autodiscovery create`, or "local" for a run of the
local CLI) and each run's saved output, either
  autodiscovery/<run>/results.json        from the hosted service (`asta autodiscovery results <run_id> -o ...`)
  autodiscovery/<run>/local/              the local CLI's --out_dir: mcts_node_*.json, rich_outputs/, args.json
both git-ignored. Writes:
  autodiscovery/runs.csv            status, settings, extract hash and shared link filled in
  autodiscovery/experiments.csv     the ranked list: within each run, rises in belief first, then falls
  autodiscovery/<run>/index.json    per-experiment text the pages quote (no code, output or ids)
  autodiscovery/<run>/figures/      the experiments' figures (git-ignored), for review before use
Stops before writing anything if a hypothesis or analysis looks like row-level data.
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
SHARED = "https://autodiscovery.allen.ai/runs/shared/{run_id}"
ROW_LEVEL = re.compile(
    r"\b(caseid|hhid|\w+_id)\s*[=:]\s*\d+|\b(row|index|record)\s*#?\s*\d{2,}\b|\bdf\.(loc|iloc)\[",
    re.I,
)
rank_key = lambda x: (
    x["belief_after"] < x["belief_before"],
    -abs(x["belief_after"] - x["belief_before"]),
)  # noqa: E731


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
    table, indexes = [], {}
    for r in rows:
        if not r["run_id"]:
            continue
        local = r["run_id"] == "local"
        if local:
            out = next(
                (
                    AD / r["run"] / n
                    for n in ("local", "raw")
                    if (AD / r["run"] / n).exists()
                ),
                AD / r["run"] / "local",
            )
            d = local_results(out)
        else:
            d = json.loads((AD / r["run"] / "results.json").read_text())
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
        figdir = AD / r["run"] / "figures"
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
            mine.append(
                {
                    "run": r["run"],
                    "experiment": n,
                    "hypothesis": e["hypothesis"],
                    "analysis": e.get("analysis") or "",
                    "belief_before": round(e["prior"], 4),
                    "belief_after": round(e["posterior"], 4),
                    "surprise": round(e.get("surprise") or 0, 4),
                    "surprising": bool(e.get("is_surprising")),
                    "link": link,
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
        table += sorted(mine, key=rank_key)
        indexes[r["run"]] = {
            "run": r["run"],
            "run_id": r["run_id"],
            "experiments": index,
        }
        print(f"{r['run']}: {r['status']}, {len(index)} experiments")
    hits = [
        (x["run"], x["experiment"], m.group(0))
        for x in table
        for f in ("hypothesis", "analysis")
        for m in ROW_LEVEL.finditer(x[f])
    ]
    if hits:
        sys.exit(
            "row-level data in the experiment text, nothing written:\n"
            + "\n".join(f"  {r}-{n}: {t!r}" for r, n, t in hits)
        )
    for run, index in indexes.items():
        (AD / run / "index.json").write_text(
            json.dumps(index, indent=1, ensure_ascii=False) + "\n"
        )
    with open(AD / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    if table:
        with open(AD / "experiments.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(table[0]))
            w.writeheader()
            w.writerows(table)
    print(f"{len(indexes)} runs, {len(table)} experiments")


if __name__ == "__main__":
    main()
