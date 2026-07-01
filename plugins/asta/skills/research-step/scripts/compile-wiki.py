#!/usr/bin/env python3
"""compile-wiki.py — render one PDF per loop of a research session.

Deterministic, no LLM. Reads every closed task's typed output_json from beads (or a
jsonl export) and, for each top-level loop under the epic root (data_provenance,
reproduction, theorizer, verification, summarize, reflection, ...), renders a
self-contained wiki page for that loop from its subtree's records, then writes
wiki_<loop>.qmd and (with --render) wiki_<loop>.pdf via Quarto. A merged wiki.qmd
concatenates every loop page into one document.

This is the per-loop companion to compile-report.py (which renders the whole-session
paper). Loop and step missions come from assets/schemas.yaml; all record wording comes
from the typed output_json. Figures referenced by ref(figure) files are embedded.

Exit: 0 ok · 1 no session / bd unavailable · 2 render failed
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMAS = HERE.parent / "assets" / "schemas.yaml"

# set in main(): the directory figures are copied into (alongside the .qmd pages),
# so Quarto resolves them by a simple relative basename regardless of cwd.
FIG_DIR = None
_fig_n = 0


def load_issues(issues_file=None):
    if issues_file:
        return [json.loads(ln) for ln in Path(issues_file).read_text().splitlines() if ln.strip()]
    try:
        out = subprocess.run(["bd", "list", "--json", "--all", "--limit", "0"],
                             capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("compile-wiki: 'bd' not found on PATH")
    except subprocess.CalledProcessError as e:
        sys.exit(f"compile-wiki: bd list failed: {e.stderr.strip()}")
    return json.loads(out)


def rs(issue):
    return (issue.get("metadata") or {}).get("research_step") or {}


def id_key(i):
    return [int(p) if p.isdigit() else p for p in str(i).split(".")]


def load_missions():
    """workflow_name -> mission, step_name -> mission, from schemas.yaml."""
    loops, steps = {}, {}
    try:
        import yaml
    except ImportError:
        return loops, steps
    doc = yaml.safe_load(SCHEMAS.read_text())
    wf = doc.get("workflows") or {}

    def walk(name, body):
        if not isinstance(body, dict):
            return
        if "mission" in body and "children" in body:
            loops.setdefault(name, body["mission"])
        for child in body.get("children") or []:
            if isinstance(child, dict) and len(child) == 1:
                cname, cbody = next(iter(child.items()))
                if isinstance(cbody, dict):
                    if "children" in cbody:
                        walk(cname, cbody)
                    elif "mission" in cbody:
                        steps.setdefault(cname, cbody["mission"])
    for name, body in wf.items():
        walk(name, body)
    return loops, steps


# ---------- markdown helpers ----------

def esc(s):
    """Escape characters that would break pandoc/LaTeX in free text."""
    if s is None:
        return ""
    s = str(s)
    for a, b in (("\\", "\\\\"), ("_", "\\_"), ("$", "\\$"), ("#", "\\#"),
                 ("%", "\\%"), ("&", "\\&"), ("{", "\\{"), ("}", "\\}"),
                 ("~", "\\textasciitilde "), ("^", "\\textasciicircum ")):
        s = s.replace(a, b)
    return s


def kv(label, value):
    return f"**{esc(label)}:** {esc(value)}\n"


def near_paths(uri):
    """Resolve a repo-root-relative path for reading (cwd is repo root)."""
    return Path(uri)


# ---------- per-type renderers ----------

def render_figure_ref(path, lines):
    p = near_paths(path)
    cap, img = "", None
    if p.is_file():
        try:
            fig = json.loads(p.read_text())
            cap, img = fig.get("caption", ""), fig.get("image")
        except (OSError, json.JSONDecodeError):
            pass
    if img and near_paths(img).is_file():
        # copy into FIG_DIR (beside the .qmd) and reference by relative basename,
        # so Quarto/LaTeX resolve it regardless of where the page is rendered.
        global _fig_n
        _fig_n += 1
        dest = FIG_DIR / f"fig{_fig_n}{near_paths(img).suffix}"
        shutil.copyfile(near_paths(img), dest)
        lines.append(f"\n![{esc(cap)}](figures/{dest.name})\n")
    elif cap:
        lines.append(f"\n*Figure: {esc(cap)}*\n")


def render_output(task_type, o, lines):
    """Type-aware rendering of one step's output_json into markdown lines."""
    if "data_sources" in o:
        for d in o["data_sources"]:
            lines.append(f"- **{esc(d.get('paper_title'))}** ({esc(d.get('paper_id'))}) — {esc(d.get('paper_url'))}\n")
    if "source_access" in o:
        for s in o["source_access"]:
            lines.append("\n" + kv("Data availability", s.get("data_availability")))
            for sr in s.get("sources") or []:
                lines.append(f"  - {esc(sr.get('repository'))}: {esc(sr.get('identifier'))}\n")
    if "acquisitions" in o:
        for a in o["acquisitions"]:
            lines.append(f"- {esc(a.get('dataset_id'))} — {esc(a.get('access_status'))}; {esc(a.get('validation_note'))}\n")
    if "datasets" in o:
        for d in o["datasets"]:
            lines.append(f"\n**Dataset {esc(d.get('id'))}** (n={esc(d.get('n'))}) — {esc(d.get('definition'))}\n")
            lines.append(kv("Source", d.get("source")))
            if d.get("covers_laws"):
                lines.append(kv("Covers laws", ", ".join(d["covers_laws"])))
    if "experiments" in o and isinstance(o["experiments"], list):
        lines.append(f"\n{len(o['experiments'])} experiment node(s) imported.\n")
    if "empirical_laws" in o:
        for law in o["empirical_laws"]:
            sup = " (surprising)" if (law.get("mcts_provenance") or {}).get("is_surprising") else ""
            lines.append(f"\n**{esc(law.get('id'))}**{sup}: {esc(law.get('statement'))}\n")
            lines.append(kv("Effect size (source)", law.get("effect_size_source")))
    if "experiment_design" in o:
        d = o["experiment_design"]
        lines.append(f"\n**{esc(d.get('experiment_name'))}** — feasibility: {esc(d.get('feasibility'))}, construct: {esc(d.get('construct_equivalence'))}\n")
        lines.append("\n" + esc(d.get("plain_language_description")) + "\n")
        ps = d.get("prespecified") or {}
        lines.append(kv("Prespecified test", ps.get("test")))
        lines.append(kv("Metric", ps.get("metric")))
        lines.append(kv("Success threshold", ps.get("success_threshold")))
        if d.get("data_gap"):
            lines.append(kv("Data gap", d.get("data_gap")))
    if "analysis" in o:
        a = o["analysis"]
        lines.append("\n" + esc(a.get("final_answer")) + "\n")
        if a.get("assumptions"):
            lines.append("\n" + kv("Assumptions", a.get("assumptions")))
    for fpath in o.get("figures") or []:
        if isinstance(fpath, str):
            render_figure_ref(fpath, lines)
    if "audit_report" in o:
        ar = o["audit_report"]
        sig = ar.get("signal") or {}
        lines.append(f"\n**Verdict: {esc(ar.get('outcome'))}** (testability: {esc(ar.get('testability'))}"
                     + (f", signal: {esc(sig.get('basis'))}" + (f" reward {esc(sig.get('reward'))}" if sig.get('reward') is not None else "") if sig else "") + ")\n")
        if ar.get("effect_size_observed"):
            lines.append(kv("Effect size observed", ar.get("effect_size_observed")))
        if ar.get("prespecified_check"):
            lines.append(kv("Prespecified check", ar.get("prespecified_check")))
        for c in ar.get("challenges") or []:
            lines.append(f"  - *{esc(c.get('concern'))}* — {esc(c.get('check'))}: {esc(c.get('outcome'))}\n")
        if ar.get("evidence"):
            lines.append("\n" + kv("Evidence", ar.get("evidence")))
    if "theories" in o:
        for t in o["theories"]:
            lines.append(f"\n**{esc(t.get('name'))}** ({esc(t.get('id'))})\n")
            lines.append("\n" + esc(t.get("description")) + "\n")
            if t.get("grounds_law_ids"):
                lines.append(kv("Grounds on laws", ", ".join(t["grounds_law_ids"])))
    if "testability_triage" in o:
        tt = o["testability_triage"]
        for a in tt.get("assessments") or []:
            sig = a.get("signal") or {}
            lines.append(f"- {esc(a.get('theory_id'))}: {esc(sig.get('basis'))} — {esc(a.get('gap') or a.get('available_data'))}\n")
        if tt.get("testable_theory_ids"):
            lines.append("\n" + kv("Testable now", ", ".join(tt["testable_theory_ids"])))
    if "theory_evaluations" in o:
        for e in o["theory_evaluations"]:
            lines.append(f"- {esc(e.get('theory_id'))}: novelty {esc(e.get('novelty'))}, support {esc(e.get('overall_support'))} — {esc(e.get('explanation'))}\n")
    if "summary" in o:
        s = o["summary"]
        lines.append(f"\n## {esc(s.get('title'))}\n")
        lines.append(kv("Discipline", s.get("discipline")) + kv("Topic", s.get("topic")))
        for para in s.get("context") or []:
            lines.append("\n" + " ".join(esc((st or {}).get("text")) for st in (para.get("sentences") or [])) + "\n")
        for au in s.get("summaries") or []:
            lines.append(f"\n**For {esc(au.get('audience'))}:** " + esc((au.get('main_finding') or {}).get('text')) + "\n")
            for st in au.get("elaboration") or []:
                lines.append("\n" + esc((st or {}).get("text")) + "\n")
    if "reflection" in o:
        r = o["reflection"]
        lines.append("\n" + kv("Session intent", r.get("session_intent")))
        if r.get("frictions"):
            lines.append("\n**Frictions**\n")
            for f in r["frictions"]:
                lines.append(f"  - [{esc(f.get('kind'))}/{esc(f.get('severity'))}] {esc(f.get('where'))}: {esc(f.get('observation'))}\n")
        if r.get("proposed_changes"):
            lines.append("\n**Proposed changes**\n")
            for c in r["proposed_changes"]:
                lines.append(f"  - [{esc(c.get('severity'))}] {esc(c.get('target'))}: {esc(c.get('change'))}\n")


# ---------- assembly ----------

def loop_page(loop_epic, issues_by_id, loop_missions, step_missions):
    """Render one loop's markdown body (heading + steps)."""
    prefix = loop_epic["id"] + "."
    name = loop_epic.get("title", loop_epic["id"])
    lines = [f"# {esc(name)}\n"]
    if loop_missions.get(name):
        lines.append("\n*" + esc(loop_missions[name]) + "*\n")
    # steps = closed task issues in this subtree, in id order
    steps = sorted(
        (i for i in issues_by_id.values()
         if i["id"].startswith(prefix) and rs(i).get("task_type") and rs(i).get("output_json")),
        key=lambda i: id_key(i["id"]))
    for st in steps:
        tt = rs(st)["task_type"]
        lines.append(f"\n## {esc(st.get('title', tt))}\n")
        render_output(tt, rs(st)["output_json"], lines)
    if len(lines) <= 2:
        lines.append("\n*(No closed steps in this loop.)*\n")
    return "".join(lines)


def qmd_doc(title, body):
    front = [
        "---", f"title: {json.dumps(title)}",
        "format:", "  pdf:", "    documentclass: article", "    fontsize: 11pt",
        "    geometry: margin=1in", "    toc: false", "---", "",
    ]
    return "\n".join(front) + "\n" + body + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", default=".", help="directory for wiki_<loop>.qmd/.pdf")
    ap.add_argument("--render", action="store_true", help="run `quarto render` per page")
    ap.add_argument("--issues", help="read a beads jsonl export instead of `bd list`")
    args = ap.parse_args(argv)

    issues = load_issues(args.issues)
    by_id = {i["id"]: i for i in issues}
    epic = next((i for i in issues if rs(i).get("epic_root")), None)
    if not epic:
        sys.exit("compile-wiki: no epic root — not a research session")
    loop_missions, step_missions = load_missions()

    root_prefix = epic["id"] + "."
    # top-level loops: direct epic children of the root, in id order
    loops = sorted(
        (i for i in issues
         if i.get("issue_type") == "epic" and i["id"].startswith(root_prefix)
         and i["id"].count(".") == epic["id"].count(".") + 1),
        key=lambda i: id_key(i["id"]))
    if not loops:
        sys.exit("compile-wiki: no top-level loops under the epic root")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    global FIG_DIR
    FIG_DIR = out_dir / "figures"
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    written, merged = [], []
    for lp in loops:
        body = loop_page(lp, by_id, loop_missions, step_missions)
        merged.append(body)
        qmd = out_dir / f"wiki_{lp['title'].strip()}.qmd"
        qmd.write_text(qmd_doc(lp["title"].strip(), body))
        written.append(qmd)
    merged_qmd = out_dir / "wiki.qmd"
    merged_qmd.write_text(qmd_doc(epic.get("title", "Research session wiki"), "\n\n\\clearpage\n\n".join(merged)))
    written.append(merged_qmd)
    print(f"compile-wiki: wrote {len(written)} qmd page(s): " + ", ".join(p.name for p in written))

    if args.render:
        failed = 0
        for qmd in written:
            try:
                subprocess.run(["quarto", "render", str(qmd), "--to", "pdf"], check=True,
                               capture_output=True, text=True)
                print(f"compile-wiki: rendered {qmd.with_suffix('.pdf').name}")
            except FileNotFoundError:
                sys.exit("compile-wiki: 'quarto' not found — install Quarto + tinytex to render PDF")
            except subprocess.CalledProcessError as e:
                failed += 1
                print(f"compile-wiki: FAILED to render {qmd.name}: {(e.stderr or '')[-600:]}", file=sys.stderr)
        if failed:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
