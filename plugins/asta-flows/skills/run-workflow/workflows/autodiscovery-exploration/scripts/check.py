"""Check the exploration's form, and that every quoted experiment text is verbatim. Exits non-zero on any failure.

    uv run --no-project --with pyyaml python -I scripts/check.py

- runs.csv and experiments.csv have the template's columns
- every page in _quarto.yml's render list is in the sidebar, and the other way round
- index.qmd and data.qmd have the template's headings, in order
- every marker in index.qmd has an evidence entry with a verbatim quote from its experiment, the run's shared link, and a page
- every internal link in index.qmd points at a file that exists
"""
import csv, glob, json, re, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RUNS_COLS = "run,round,label,title,run_id,prompt,sub_questions,files,extract_hash,n_experiments,exploration_weight,surprisal_width,evidence_weight,status,shared_url,decision".split(",")
EXP_COLS = "run,experiment,hypothesis,analysis,belief_before,belief_after,surprise,surprising,link".split(",")
INDEX_HEADINGS = ["## Prompt", "## Data", "## Runs", "## Findings", "## Null results", "## Next steps"]  # Answers is optional
DATA_HEADINGS = ["## Source", "## Extract", "## Files", "## Description", "## Columns"]
norm = lambda s: " ".join(str(s).split())  # noqa: E731
errors = []


def headings(path, expected):
    found = [l.strip() for l in path.read_text().splitlines() if l.startswith("## ")]
    seq = [h for h in found if h in expected]
    if seq != [h for h in expected if h in found] or any(h not in found for h in expected):
        errors.append(f"{path.name}: headings are {found}; the template wants {expected} in that order")


def main():
    for name, cols in (("runs.csv", RUNS_COLS), ("experiments.csv", EXP_COLS)):
        p = ROOT / "autodiscovery" / name
        if not p.exists():
            errors.append(f"{name} missing"); continue
        have = next(csv.reader(open(p)))
        if have != cols:
            errors.append(f"{name}: columns {have} differ from the template's {cols}")
    q = yaml.safe_load((ROOT / "_quarto.yml").read_text())
    rendered = set()
    for pat in q["project"]["render"]:
        rendered |= {str(Path(f).relative_to(ROOT)) for f in glob.glob(str(ROOT / pat))}
    side = ROOT / "_generated/sidebar.yml"
    listed = set(re.findall(r"(?:href:\s*|-\s+)(\S+\.qmd)", side.read_text())) if side.exists() else set()
    for missing in sorted(rendered - listed):
        errors.append(f"{missing} renders but is not in the sidebar")
    for extra in sorted(listed - rendered):
        errors.append(f"{extra} is in the sidebar but does not render")
    headings(ROOT / "index.qmd", INDEX_HEADINGS)
    if (ROOT / "data.qmd").exists():
        headings(ROOT / "data.qmd", DATA_HEADINGS)
    text = (ROOT / "index.qmd").read_text()
    ev = (yaml.safe_load((ROOT / "evidence.yml").read_text()) or {}).get("evidence", {})
    runs = {r["label"]: r for r in csv.DictReader(open(ROOT / "autodiscovery/runs.csv"))}
    indexes = {}
    for key in sorted(set(re.findall(r'\.ev key="([^"]+)"', text))):
        v = ev.get(key)
        if v is None:
            errors.append(f"marker {key}: no evidence entry"); continue
        m = re.search(r"run (\w+), experiment (\d+)", v.get("source", ""))
        if not m:
            continue  # a literature entry
        label, n = m.group(1), int(m.group(2))
        r = runs.get(label)
        if r is None:
            errors.append(f"{key}: no run labelled {label}"); continue
        if r["run"] not in indexes:
            indexes[r["run"]] = {e["experiment"]: e for e in json.loads((ROOT / "autodiscovery" / r["run"] / "index.json").read_text())["experiments"]}
        e = indexes[r["run"]].get(n)
        if e is None:
            errors.append(f"{key}: run {label} has no experiment {n}"); continue
        if norm(v["quote"]) not in norm(" ".join([e["hypothesis"], e["analysis"], e.get("review", "")])):
            errors.append(f"{key}: quote not verbatim in {label}-{n}")
        if e["link"] and v.get("url") != e["link"]:
            errors.append(f"{key}: url is not the experiment's shared link")
        if not e["link"] and v.get("url"):
            errors.append(f"{key}: the run was local, so the entry should have no url")
        if v.get("page") != f"runs/{r['run']}.qmd":
            errors.append(f"{key}: page should be runs/{r['run']}.qmd")
    for target in set(re.findall(r"\]\(([^)#\s]+)\)", text)):
        if target.startswith(("http", "mailto")):
            continue
        if not (ROOT / target).exists():
            errors.append(f"index.qmd links to {target}, which does not exist")
    print("\n".join(errors) if errors else "form and quotes check out")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
