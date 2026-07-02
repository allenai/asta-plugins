#!/usr/bin/env python3
"""compile-report.py — render a research session into a publication-quality report.

Deterministic, no LLM. Reads every closed task's typed output_json from beads (or a
jsonl export), joins the primary records by id (laws⨝audits,
theories⨝novelty⨝audit, hypotheses⨝audit, provenance, analyses), and
renders an academic paper via Jinja section templates in assets/templates/report/:
Abstract → Methods → Results (per-law / per-theory, verdicts inline, stats prominent)
→ Trustworthiness → Appendices. All wording lives in the templates; this module joins
the data and assembles the document with LaTeX typography. Quarto renders to PDF.

Exit: 0 ok · 1 no session / bd unavailable · 2 render failed
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMAS = HERE.parent / "assets" / "workflows.yaml"
REPORT_TMPL = HERE.parent / "assets" / "templates" / "report"
LOGO = HERE.parent / "assets" / "asta-logo.pdf"  # Asta (Ai2) brand mark

sys.path.insert(0, str(HERE))
import render  # noqa: E402

# ordered paper sections (template stem in assets/templates/report/); blank renders skipped
SECTIONS = [
    "mission", "abstract", "methods", "results_laws", "results_theories",
    "appendix_theories", "appendix_hypotheses",
    "appendix_experiments", "appendix_datasets", "appendix_references",
]

FLOW_SUBTITLE = {
    "data_and_literature_grounded_theory_generation":
        "Reproduction and literature-grounded theory generation over an AutoDiscovery run",
    "auto_discovery": "Cohort assembly, AutoDiscovery, and held-out replication",
}


# ---------- beads ----------

def load_issues(issues_file=None):
    if issues_file:
        return [json.loads(ln) for ln in Path(issues_file).read_text().splitlines() if ln.strip()]
    try:
        out = subprocess.run(["bd", "list", "--json", "--all", "--limit", "0"],
                             capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("compile-report: 'bd' not found on PATH")
    except subprocess.CalledProcessError as e:
        sys.exit(f"compile-report: bd list failed: {e.stderr.strip()}")
    return json.loads(out)


def id_key(i):
    return [int(p) if p.isdigit() else p for p in str(i).split(".")]


def rs(issue):
    return (issue.get("metadata") or {}).get("research_step") or {}


class Session:
    def __init__(self, issues):
        self.epic = next((i for i in issues if rs(i).get("epic_root")), None)
        if not self.epic:
            sys.exit("compile-report: no epic root — not a research session")
        self.loop = self.flow = rs(self.epic).get("flow", "")
        prefix = self.epic["id"] + "."
        self.tasks = sorted(
            (i for i in issues if i["id"].startswith(prefix)
             and rs(i).get("task_type") and rs(i).get("output_json")
             and i.get("status") == "closed"),
            key=lambda i: id_key(i["id"]),
        )


# ---------- entity → link resolution ----------

def _pref(uri, base_url):
    return (base_url.rstrip("/") + "/" + uri.lstrip("/")) if base_url else uri


def _existing(uri, near=""):
    """The uri if its file exists, else a sibling in the same directory whose name starts
    with `near` (the entity's short id). Repairs runs whose recorded artifact uri drifted
    from the file actually written (e.g. L1_result.json recorded, L1_analysis.md written),
    so the report never links a missing file. None if neither resolves."""
    if not uri:
        return None
    if Path(uri).exists():
        return uri
    d = Path(uri).parent
    if near and d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.name.startswith(near):
                return p.as_posix()
    return None


def art_link(art, base_url="", near=""):
    """The best link for an artifact: its Asta-UX share URL when present (populated by
    the backend), else its local file part — existence-checked, optionally base-url prefixed.
    Always resolved (so the report can show the result label); whether the label is
    rendered as a clickable hyperlink is decided per output by `clickable` (see build)."""
    if not art:
        return None
    meta = art.get("metadata") or {}
    if meta.get("share_url"):
        return meta["share_url"]
    for p in art.get("parts") or []:
        if p.get("kind") == "file":
            uri = _existing((p.get("file") or {}).get("uri"), near)
            if uri:
                return _pref(uri, base_url)
    return None


def _art_of_type(output_json, kind):
    return next((a for a in output_json.get("artifacts") or []
                 if (a.get("metadata") or {}).get("type") == kind), None)


def _doi_url(s):
    """Pull a resolvable URL out of a free-text source/identifier string (DOI or http)."""
    if not s:
        return None
    m = re.search(r"10\.\d{4,9}/[^\s)\";]+", s)
    if m:
        return "https://doi.org/" + m.group(0).rstrip(".,);")
    m = re.search(r"https?://[^\s)\"]+", s)
    return m.group(0).rstrip(".,);") if m else None


# Figures the producing agent flagged as empty/unrendered — a blank axes with a
# "the plot is empty" caption is noise in a shareable report, so they're dropped.
_EMPTY_FIG_RE = re.compile(r"(?i)\bempty\b|\bunrendered\b|no data|missing data")


def _useful_fig(f):
    return bool(f.get("image")) and not _EMPTY_FIG_RE.search(f.get("caption") or "")


def _fig_id(f):
    """Content identity for figure dedup: the image bytes' hash when the file is readable,
    else the image path. Two branches that emit the exact same plot show it once."""
    img = f.get("image") or ""
    p = Path(img)
    if p.is_file():
        try:
            import hashlib
            return hashlib.md5(p.read_bytes()).hexdigest()
        except Exception:
            pass
    return img


def _deref(x):
    """A typed-output list item may be an inline object or a repo-root-relative path to a
    JSON file (an x-path-ref, per the output schema — e.g. figures: [ref(figure)],
    experiments: [ref(experiment)]). Load the file when it's a path so the renderer always
    sees the object, whichever form the task emitted."""
    if isinstance(x, str):
        p = Path(x)
        if p.is_file():
            try:
                return json.loads(p.read_text())
            except Exception:
                return {}
    return x


# ---------- verdict ordering & badges (generic; keyed off the workflows.yaml vocabulary) ----------
#
# All of the following read only the vocabulary enums (outcome / testability / novelty /
# signal_basis) defined in assets/workflows.yaml. No subject ids, dataset names, or domain
# terms appear here, so the ordering and badges behave identically for any flow's records.

# rank so the strongest, most-tested, most-novel items lead their section; unknowns sort last
_OUTCOME_RANK = {"held": 0, "partial": 1, "underpowered": 2, "failed": 3, "n/a": 4}
_TEST_RANK = {"tested": 0, "proxy_only": 1, "untestable": 2}
_NOVELTY_RANK = {"genuinely_new": 0, "derivable": 1, "established": 2}
# the Theorizer's per-statement novelty class (theory_components.theory_statements[].
# novelty_evaluation.likely_classification) — the statement-level signal we now surface/sort by
_STMT_NOVELTY_RANK = {"new": 0, "somewhat-related-to-existing": 1, "closely-related-to-existing": 2}

# outcome → (colour token defined in header_includes, short label)
_BADGE = {
    "held": ("ai2accent", "held"), "partial": ("ai2amber", "partial"),
    "underpowered": ("ai2amber", "underpowered"), "failed": ("ai2red", "failed"),
    "n/a": ("ai2gray", "untestable"),
}


def _law_sort_key(x):
    v = x.get("verdict") or {}
    return (_OUTCOME_RANK.get(v.get("outcome"), 5), _TEST_RANK.get(v.get("testability"), 3))


def _theory_statements(t):
    """The Theorizer's per-statement records — name, text, and the statement-level novelty class —
    read from the theory's carried theory_components (components_path ref). These statements are the
    granularity the novelty accessor scores; empty when the components file is absent."""
    comp = _deref(t.get("components_path"))
    out = []
    if isinstance(comp, dict):
        for s in comp.get("theory_statements") or []:
            ne = s.get("novelty_evaluation") or {}
            out.append({"name": s.get("statement_name"), "text": s.get("theory_statement"),
                        "novelty": ne.get("likely_classification"),
                        "what_is_novel": ne.get("what_is_novel")})
    return out


def _theory_sort_key(t):
    # testable-now first, then by the theory's most-novel statement (statement-level novelty);
    # theories with no statement-level novelty (e.g. accuracy-focused) sort last within their group
    testable = 0 if ((t.get("eval") or {}).get("signal") or {}).get("basis") == "testable" else 1
    nov = t.get("novelty_rank")
    return (testable, nov if nov is not None else 3)


def verdict_badge(outcome=None, testability=None):
    """A \\vbadge[colour]{LABEL} LaTeX call for a two-axis verdict; untestable overrides the
    outcome colour. Empty string when there is no verdict, so templates may call it freely."""
    if not outcome:
        return ""
    if testability == "untestable" or outcome == "n/a":
        color, label = "ai2gray", "untestable"
    else:
        color, label = _BADGE.get(outcome, ("ai2gray", outcome))
    return r"\vbadge[%s]{%s}" % (color, label.upper())


def triage_badge(basis=None):
    """Badge for a theory's testability triage (signal.basis ∈ testable / untestable)."""
    if basis == "testable":
        return r"\vbadge[ai2accent]{TESTABLE NOW}"
    if basis == "untestable":
        return r"\vbadge[ai2gray]{NEEDS NEW DATA}"
    return ""


# statement/law-level novelty badge, keyed by the Theorizer's native likely_classification
_NOVELTY_BADGE = {
    "new": ("ai2accent", "NEW"),
    "somewhat-related-to-existing": ("ai2amber", "DERIVABLE"),
    "closely-related-to-existing": ("ai2gray", "ESTABLISHED"),
    # tolerate the schema-enum vocabulary too, so the badge renders either way
    "genuinely_new": ("ai2accent", "NEW"),
    "derivable": ("ai2amber", "DERIVABLE"),
    "established": ("ai2gray", "ESTABLISHED"),
}


def novelty_badge(cls=None):
    """A \\vbadge for a single law/statement's novelty class; empty string when unscored."""
    if not cls:
        return ""
    color, label = _NOVELTY_BADGE.get(cls, ("ai2gray", str(cls).upper()))
    return r"\vbadge[%s]{%s}" % (color, label)


def novelty_tag(cls=None):
    """A lightweight coloured caps tag for a law's novelty inside a dense LaTeX table (no box —
    boxes crowd a longtable cell). Returns a faint em dash when the law is unscored."""
    if not cls:
        return r"{\color{ai2gray}\small ---}"
    color, label = _NOVELTY_BADGE.get(cls, ("ai2gray", str(cls).upper()))
    return r"{\footnotesize\sffamily\bfseries\color{%s}%s}" % (color, label)


def outcome_tag(outcome=None, testability=None):
    """A coloured caps verdict tag (outcome + testability) for the hypotheses table — same
    palette as the boxed \\vbadge but as lightweight text, matching the theory-table tags."""
    if not outcome:
        return ""
    if testability == "untestable" or outcome == "n/a":
        return r"{\footnotesize\sffamily\bfseries\color{ai2gray}UNTESTABLE}"
    color, label = _BADGE.get(outcome, ("ai2gray", str(outcome)))
    tail = r"\ {\footnotesize\color{ai2gray}%s}" % testability.replace("_", " ") if testability else ""
    return r"{\footnotesize\sffamily\bfseries\color{%s}%s}%s" % (color, label.upper(), tail)


def triage_tag(basis=None):
    """A compact caps testability tag for a theory row's Testability column."""
    if basis == "testable":
        return r"{\footnotesize\sffamily\bfseries\color{ai2accent}TESTABLE}"
    if basis == "untestable":
        return r"{\footnotesize\sffamily\bfseries\color{ai2gray}NEEDS DATA}"
    return ""


def short(text, n=140):
    """Word-boundary truncation that strips trailing punctuation before the ellipsis, so a
    clause already ending in '.' never renders a dot-run (replaces a fragile split+truncate)."""
    s = re.sub(r"\s+", " ", (text or "").strip())
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" ,;:.-([") + "…"


# ---------- join records into a render context ----------

def collect(sess, base_url=""):
    def out(tt):
        return [rs(i)["output_json"] for i in sess.tasks if rs(i)["task_type"] == tt]

    laws, theories = [], []
    for tt in ("auto_discovery", "discovery_run"):
        for o in out(tt):
            laws += o.get("autods_hypotheses") or []
    for o in out("theory_generation"):  # one Theorizer run per generation objective (fan-out)
        store = _art_of_type(o, "theory_store")  # theory cites the store file that formed it
        for t in o.get("theories") or []:
            t["link"] = art_link(store, base_url)
            t["grounds"] = t.get("grounds_hypothesis_ids") or []
            # statement-level novelty (the Theorizer's own per-statement class) and the theory's
            # most-novel statement, used to sort and to render the per-statement novelty view
            t["statements"] = _theory_statements(t)
            ranks = [_STMT_NOVELTY_RANK[s["novelty"]] for s in t["statements"]
                     if s.get("novelty") in _STMT_NOVELTY_RANK]
            t["novelty_rank"] = min(ranks) if ranks else None
            t["top_novelty"] = next((n for r, n in
                                     sorted((_STMT_NOVELTY_RANK[s["novelty"]], s["novelty"])
                                            for s in t["statements"] if s.get("novelty") in _STMT_NOVELTY_RANK)),
                                    None)
            theories.append(t)

    # novelty_assessment now carries the testability triage too (formerly a separate
    # testability_triage task), so one theory_evaluation serves as both eval and triage.
    evals, triage = {}, {}
    for o in out("novelty_assessment"):
        for e in o.get("theory_evaluations") or []:
            evals[e.get("theory_id")] = triage[e.get("theory_id")] = e

    # audit now carries both the refutation and the finalized verdict (formerly a
    # separate critique), so one audit_report serves as both verdict and audit.
    audits = {}
    for tt in ("audit", "holdout_replication"):
        for o in out(tt):
            ar = o.get("audit_report")
            if ar and ar.get("subject_id"):
                audits[ar["subject_id"]] = ar

    # designs, figures, and the DataVoyager result, associated to a subject via the branch group
    designs, figs, dv, issue_subject = {}, {}, {}, {}
    seen_fig = set()  # global figure dedup: an identical image (by content) is shown once
    groups = {}
    for i in sess.tasks:
        groups.setdefault(i["id"].rsplit(".", 1)[0], []).append(i)
    for members in groups.values():
        subj = None
        for m in members:
            o = rs(m)["output_json"]
            if rs(m)["task_type"] in ("audit", "holdout_replication"):
                subj = (o.get("audit_report") or {}).get("subject_id") or subj
            if rs(m)["task_type"] == "experiment_design":
                ed = o.get("experiment_design") or {}
                if ed.get("subject_id"):
                    designs[ed["subject_id"]] = ed
        if subj:
            for m in members:  # every step of this branch points at the subject's report section
                issue_subject[m["id"]] = subj
            for m in members:
                o = rs(m)["output_json"]
                for f in (_deref(x) for x in (o.get("figures") or [])):
                    if _useful_fig(f) and _fig_id(f) not in seen_fig:
                        seen_fig.add(_fig_id(f))
                        figs.setdefault(subj, []).append(f)
                if rs(m)["task_type"] in ("analysis", "holdout_replication"):  # the test that decided the verdict
                    link = art_link(_art_of_type(o, "widget_data_voyager"), base_url,
                                    near=(subj.split("_")[0] if subj else ""))
                    if link and subj not in dv:
                        dv[subj] = link

    def enrich(items):
        for x in items:
            i = x.get("id")
            x["verdict"] = x["audit"] = audits.get(i)
            x["design"], x["figs"] = designs.get(i), figs.get(i, [])
            x["eval"], x["triage"] = evals.get(i), triage.get(i)
            if not x.get("link"):  # theories already carry their theory-store link
                x["link"] = dv.get(i)
        return items

    enrich(laws)
    enrich(theories)

    datasets, experiments, citations = {}, [], {}
    for i in sess.tasks:
        o = rs(i)["output_json"]
        for ds in o.get("datasets") or []:
            if ds.get("id"):
                datasets.setdefault(ds["id"], ds)
        experiments += [_deref(e) for e in (o.get("experiments") or [])]
    for o in out("thematic_search"):  # the literature_search fan-out grounds the references
        for c in (o.get("literature_review") or {}).get("citations") or []:
            citations.setdefault(c.get("corpus_id") or c.get("id") or c.get("title"), c)

    run_id = ""
    for o in out("cohort_assembly") + out("auto_discovery"):
        run_id = (o.get("cohort") or {}).get("run_id", "") or run_id
    datasets = list(datasets.values())
    primary = max(datasets, key=lambda d: d.get("n") or 0) if datasets else None

    # per-hypothesis independent datasets, from the structured covers map (dataset → hypothesis ids).
    # Surfaced so the reader sees which independent data decided each.
    law_ds = {}
    for d in datasets:
        for lid in d.get("covers_hypotheses") or []:
            law_ds.setdefault(lid, []).append(d.get("id") or (d.get("source") or "").split(",")[0])
    for x in laws:
        x["datasets"] = law_ds.get(x.get("id"), [])

    # reverse edges for cross-navigation (all derived from existing id-lists; no schema change):
    # hypothesis -> theories that ground on it, and dataset -> hypotheses it tested.
    law_ids = {x.get("id") for x in laws}
    ds_by_id = {d.get("id"): d for d in datasets}
    hyp_theories = {}
    for t in theories:
        for gid in t.get("grounds_hypothesis_ids") or []:
            if gid in law_ids:
                hyp_theories.setdefault(gid, []).append(t.get("id"))
    for i, d in enumerate(datasets, 1):
        did = d.get("id") or ""
        # compact table label: reuse a leading DS#/D# token if the id has one, else assign D1..Dn.
        # (Full ids can be long, unbreakable tokens that overflow the narrow table columns.)
        m = re.match(r"(DS\d+|D\d+)", did)
        d["short"] = m.group(1) if m else "D%d" % i
        d["tests"] = [h for h in (d.get("covers_hypotheses") or []) if h in law_ids]
    for x in laws:
        x["grounding_theories"] = hyp_theories.get(x.get("id"), [])
        x["dataset_chips"] = [{"id": did, "label": (ds_by_id[did]["short"] if did in ds_by_id else did)}
                              for did in x.get("datasets", [])]

    # lead each section with the strongest results (held/tested, then testable-now theories)
    laws.sort(key=_law_sort_key)

    # experiments cite the AutoDiscovery run: a per-node file when present, else the run's node table
    run_dir = ""
    for o in out("auto_discovery") + out("discovery_run"):
        for a in o.get("artifacts") or []:
            for p in a.get("parts") or []:
                uri = (p.get("file") or {}).get("uri", "") if p.get("kind") == "file" else ""
                if "mcts" in uri or uri.startswith("inputs/"):
                    run_dir = uri.rsplit("/", 1)[0]
                    break
            if run_dir:
                break
        if run_dir:
            break
    if not run_id and run_dir:  # recover the AutoDiscovery run id from inputs/<run_id>/ paths
        m = re.search(r"[0-9a-fA-F-]{8,}", Path(run_dir).name)
        run_id = m.group(0) if m else run_id
    for e in experiments:
        eid = e.get("experiment_id")
        link = None
        if run_dir:
            node = f"{run_dir}/mcts_node_{eid}.json"
            if Path(node).exists():
                link = _pref(node, base_url)
            elif Path(f"{run_dir}/mcts_nodes.csv").exists():
                link = _pref(f"{run_dir}/mcts_nodes.csv", base_url)
        e["link"] = link

    def tally(items):
        v = [x["verdict"] for x in items if x.get("verdict")]
        return {
            "n": len(items), "tested": len(v),
            "held": sum(1 for a in v if a.get("outcome") == "held"),
            "partial": sum(1 for a in v if a.get("outcome") == "partial"),
            "failed": sum(1 for a in v if a.get("outcome") == "failed"),
            "untestable": sum(1 for a in v
                              if a.get("outcome") == "n/a" or a.get("testability") == "untestable"),
        }

    # references, segmented Papers / Datasets — resolvable identifiers only, deduped.
    # Papers = the literature_search citations. Datasets = registered dataset records with a DOI.
    def _key(u):
        return re.sub(r"[#?].*$", "", (u or "").rstrip("/"))

    ref_papers, ref_datasets = {}, {}
    for c in citations.values():
        if c.get("url") and c.get("title"):
            ref_papers.setdefault(_key(c["url"]), {"name": c["title"], "url": c["url"]})

    _paper_names = {(p["name"] or "").strip().lower() for p in ref_papers.values()}

    def add_dataset(name, url):  # only archives with their OWN identifier (not a paper already listed)
        if not (url and name) or _key(url) in ref_papers:
            return
        nm = name.strip()
        # never list a source paper as a dataset, and never list the same-named archive twice
        # (multiple data_sources can carry the same paper_title with different product DOIs)
        if nm.lower() in _paper_names:
            return
        if any(d["name"].strip().lower() == nm.lower() for d in ref_datasets.values()):
            return
        ref_datasets.setdefault(_key(url), {"name": nm, "url": url})

    for d in datasets:  # registered datasets with a resolvable identifier
        url = _doi_url(d.get("source"))
        name = ((d.get("source") or "").split(",")[0].split(" doi")[0].split(";")[0].strip()
                or (d.get("definition") or "").split(":")[0].strip() or d.get("id"))
        add_dataset(name[:90], url)

    # overview/summary figures (recursive scan), mapped to a section by producing task
    def find_figs(o):
        f = []
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "figures" and isinstance(v, list):
                    f += [d for d in (_deref(x) for x in v) if isinstance(d, dict) and _useful_fig(d)]
                else:
                    f += find_figs(v)
        elif isinstance(o, list):
            for v in o:
                f += find_figs(v)
        return f

    overview = {}
    # only summary figures worth a section overview; per-law/theory plots carry the laws
    fig_section = {"theory_synthesis": "theories", "final_synthesis": "theories"}
    for i in sess.tasks:
        sec = fig_section.get(rs(i)["task_type"])
        if sec and sec not in overview:
            ff = find_figs(rs(i)["output_json"])
            if ff:
                overview[sec] = ff[0]

    def ids_where(items, pred):
        return [x.get("id") for x in items if x.get("verdict") and pred(x["verdict"])]

    verified = [t for t in theories if t.get("verdict")]
    definitional = [t.get("id") for t in verified if t.get("audit")
                    and any(w in (t["audit"].get("recommended_adjustment") or "").lower()
                            for w in ("construction", "definitional"))]
    testable_theories = [t for t in theories
                         if (t.get("eval") or {}).get("signal", {}).get("basis") == "testable"]

    summary = next((rs(i)["output_json"].get("summary")
                    for i in sess.tasks if rs(i)["task_type"] == "summarize"), None)

    return {
        "flow": sess.flow,
        "summary": summary,
        "task_types": {rs(i)["task_type"] for i in sess.tasks},
        "laws": laws, "theories": theories,
        "law_stats": tally(laws), "theory_stats": tally(theories),
        "n_theories": len(theories),
        "n_testable_theories": len(testable_theories),
        "objectives": sorted({t.get("objective") for t in theories if t.get("objective")}),
        "verified_theories": verified,
        "theories_ordered": sorted(theories, key=_theory_sort_key),
        "held_law_ids": ids_where(laws, lambda v: v.get("outcome") == "held"),
        "held_theory_ids": ids_where(theories, lambda v: v.get("outcome") == "held"),
        "definitional_ids": definitional,
        "ref_papers": list(ref_papers.values()), "ref_datasets": list(ref_datasets.values()),
        "issue_subject": issue_subject,
        "overview": overview,
        "datasets": datasets, "experiments": experiments, "citations": list(citations.values()),
        "run_id": run_id, "primary_dataset": primary,
        "agents_used": _agents(sess),
    }


def _agents(sess):
    used = set()
    chains = {
        "asta autodiscovery": "AutoDiscovery", "asta analyze-data": "DataVoyager",
        "asta generate-theories": "Theorizer", "asta literature": "Paper Finder",
        "asta papers": "Semantic Scholar", "asta experiment": "AutoExperimentDesigner",
    }
    # infer from task types present (chains aren't in the issue, but task types imply agents)
    tt = {rs(i)["task_type"] for i in sess.tasks}
    if {"auto_discovery", "discovery_run", "cohort_assembly"} & tt:
        used.add("AutoDiscovery")
    if {"analysis", "holdout_replication"} & tt:
        used.add("DataVoyager")
    if {"theory_generation", "theory_formation", "novelty_assessment"} & tt:
        used.add("Theorizer")
    if {"thematic_search", "literature_search", "cohort_assembly", "literature_review", "provenance_search"} & tt:
        used.add("Paper Finder")
    if "experiment_design" in tt:
        used.add("AutoExperimentDesigner")
    return sorted(used)


# ---------- typography ----------

_GLYPHS = {
    "∝": r"\ensuremath{\propto}", "≈": r"\ensuremath{\approx}", "≤": r"\ensuremath{\leq}",
    "≥": r"\ensuremath{\geq}", "≠": r"\ensuremath{\neq}", "×": r"\ensuremath{\times}",
    "±": r"\ensuremath{\pm}", "·": r"\ensuremath{\cdot}", "−": r"\ensuremath{-}",
    "→": r"\ensuremath{\rightarrow}", "≫": r"\ensuremath{\gg}", "≪": r"\ensuremath{\ll}",
    "Δ": r"\ensuremath{\Delta}", "∈": r"\ensuremath{\in}", "√": r"\ensuremath{\surd}",
    "α": r"\ensuremath{\alpha}", "β": r"\ensuremath{\beta}", "γ": r"\ensuremath{\gamma}",
    "τ": r"\ensuremath{\tau}", "σ": r"\ensuremath{\sigma}", "μ": r"\ensuremath{\mu}",
    "ρ": r"\ensuremath{\rho}", "θ": r"\ensuremath{\theta}", "λ": r"\ensuremath{\lambda}",
    "²": r"\textsuperscript{2}", "³": r"\textsuperscript{3}", "¹": r"\textsuperscript{1}",
    "⁰": r"\textsuperscript{0}", "⁴": r"\textsuperscript{4}", "⁵": r"\textsuperscript{5}",
    "⁶": r"\textsuperscript{6}", "⁷": r"\textsuperscript{7}", "⁸": r"\textsuperscript{8}",
    "⁹": r"\textsuperscript{9}", "⁻": r"\textsuperscript{-}",
}


def header_includes(short_title):
    """Ai2 print identity (modeled on allenai/latex-template, ai2_paper): Manrope sans
    titles and headings, pink title, teal links, cream accent, serif body. flushbottom
    so pages fill instead of leaving ragged gaps."""
    short = re.sub(r'["“”]', "", re.sub(r"[#%&_${}\\~^]", " ", short_title)).strip()
    if len(short) > 46:
        short = short[:46].rsplit(" ", 1)[0] + "…"
    assets = LOGO.parent
    logo = str(LOGO).replace("\\", "/")
    manrope = str(assets / "fonts" / "manrope").replace("\\", "/")
    lines = [r"\PassOptionsToPackage{dvipsnames,svgnames}{xcolor}", r"\usepackage{newunicodechar}"]
    lines += [r"\newunicodechar{" + ch + "}{" + repl + "}" for ch, repl in _GLYPHS.items()]
    lines += [
        # Ai2 / Asta palette — official AllenAI Varnish design tokens
        # (allenai/varnish: packages/varnish-theme/tokens/color/base.cjs)
        r"\definecolor{ai2pink}{HTML}{F0529C}",       # brand pink (logos, storybook)
        r"\definecolor{ai2accent}{HTML}{407579}",     # Asta teal accent
        r"\definecolor{ai2foreground}{HTML}{1C2B33}", # body ink
        r"\definecolor{ai2background}{HTML}{FAF2E9}", # Asta cream
        r"\definecolor{ai2dark}{HTML}{0A3235}",       # Varnish dark-teal
        r"\definecolor{ai2extradark}{HTML}{032629}",  # Varnish extra-dark-teal
        r"\definecolor{ai2tealtint}{HTML}{E7EEEE}",   # light teal wash for phase containers
        r"\definecolor{ai2amber}{HTML}{B8860B}",      # verdict badge: partial / underpowered
        r"\definecolor{ai2red}{HTML}{B03A2E}",        # verdict badge: failed
        r"\definecolor{ai2gray}{HTML}{6B7280}",       # verdict badge: untestable / needs data
        # Manrope for the sans family (title + headings); body stays serif
        r"\usepackage{fontspec}",
        r"\setsansfont{Manrope}[Path=" + manrope + r"/, Extension=.ttf, "
        r"UprightFont=Manrope-Regular, BoldFont=Manrope-Bold, "
        r"ItalicFont=Manrope-Italic, BoldItalicFont=Manrope-BoldItalic]",
        # sans, bold, dark headings (ai2 titleformat)
        r"\usepackage{sectsty}",
        r"\allsectionsfont{\sffamily\bfseries\color{ai2foreground}}",
        r"\AtBeginDocument{\hypersetup{colorlinks=true,linkcolor=ai2accent,citecolor=ai2accent,urlcolor=ai2accent,filecolor=ai2accent}}",
        # title block: Huge pink Manrope, left-aligned; author in dark sans (ai2 \title)
        r"\usepackage{titling}",
        r"\setlength{\droptitle}{-3em}",
        r"\pretitle{\begin{flushleft}\Huge\sffamily\bfseries\color{ai2pink}}",
        r"\posttitle{\par\end{flushleft}\vskip 0.4em}",
        r"\preauthor{\begin{flushleft}\large\sffamily\bfseries\color{ai2foreground}}",
        r"\postauthor{\par\vskip 2pt {\normalsize\sffamily\mdseries\color{ai2foreground}Allen Institute for AI}\par\end{flushleft}}",
        r"\predate{}\postdate{}\date{}",
        r"\usepackage{graphicx}",
        r"\usepackage{tikz}",
        r"\usetikzlibrary{arrows.meta,positioning}",
        # cream Ai2 "Abstract"-style box, used for the Scientific Context
        r"\usepackage[most]{tcolorbox}",
        r"\newtcolorbox{contextbox}{colback=ai2background,colframe=ai2background,boxrule=0pt,"
        r"arc=3mm,left=5mm,right=5mm,top=2.5mm,bottom=2.5mm,"
        r"before upper={\setlength{\parskip}{0.5em}\setlength{\parindent}{0pt}}}",
        # inline verdict badge (\vbadge[colour]{LABEL}); colour defaults to the teal accent
        r"\newtcbox{\vbadge}[1][ai2accent]{on line, colframe=#1, colback=#1!12, "
        r"boxrule=0.4pt, arc=2pt, boxsep=0pt, left=3pt, right=3pt, top=1pt, bottom=0.5pt, "
        r"fontupper=\scriptsize\sffamily\bfseries\color{#1}}",
        # keep figures in the subsection that owns them (no spill into the next result)
        r"\usepackage{float}",
        r"\renewcommand{\contentsname}{Contents}",
        r"\usepackage{fancyhdr}",
        r"\newcommand{\astalogo}{\raisebox{-2.5pt}{\includegraphics[height=11pt]{" + logo + r"}}}",
        r"\renewcommand{\headrule}{\hbox to\headwidth{\color{ai2pink}\leaders\hrule height 1pt\hfill}}",
        r"\pagestyle{fancy}\fancyhf{}",
        r"\fancyhead[L]{\astalogo}",
        r"\fancyhead[R]{\small\itshape\color{ai2dark}" + short + "}",
        r"\fancyfoot[L]{\footnotesize\color{gray}Generated by Asta · Allen Institute for AI}",
        r"\fancyfoot[R]{\footnotesize\color{gray}\thepage}",
        # title page (plain) stays clean: no top header/rule (frees vertical space), brand in the footer
        r"\fancypagestyle{plain}{\fancyhf{}"
        r"\fancyfoot[L]{\footnotesize\color{gray}Generated by Asta · Allen Institute for AI}"
        r"\fancyfoot[R]{\footnotesize\color{gray}\thepage}"
        r"\renewcommand{\headrule}{}}",
        # ragged bottom so spare space falls to the page foot rather than stretching the
        # gaps around figures/headings (front-matter pages are bounded by \clearpage instead)
        r"\setlength{\parindent}{0pt}\setlength{\parskip}{0.5em}",
        r"\raggedbottom\widowpenalty=1000\clubpenalty=1000",
    ]
    return lines


def title_from_mission(default):
    p = Path("mission.md")
    if p.is_file():
        for line in p.read_text().splitlines():
            s = line.strip()
            if s.startswith("#"):
                return re.sub(r"^#+\s*", "", s).strip()
            if s:
                return s[:140]
    return default


def mission_intro():
    """The 'Research question' framing from mission.md (operational sections omitted)."""
    p = Path("mission.md")
    if not p.is_file():
        return ""
    text = p.read_text()
    m = re.search(r"(?ims)^#+\s*(?:research question|question|motivation|background)\s*\n(.+?)(?=\n#+\s|\Z)", text)
    if m:
        return m.group(1).strip()
    return ""


def _tex(s):
    s = "" if s is None else str(s)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"),
                 ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}")):
        s = s.replace(a, b)
    return s


def _parse_flow_mmd(flow):
    """Parse assets/compiled/<flow>.mmd (the generated mermaid for the flow) into ordered
    phases. Returns ([(phase_label, [(task_id, task_label), ...]), ...], fanout_ids) where
    top-level mermaid subgraphs are phases, their nodes are tasks, thick (==>) edges between
    top-level subgraphs give phase order, and tasks inside a nested subgraph (a fan-out) are
    collected in fanout_ids. The diagram is thus derivable from — and never drifts from — the
    flow definition."""
    path = HERE.parent / "assets" / "compiled" / f"{flow}.mmd"
    if not path.is_file():
        return [], set()
    text = path.read_text()
    node_label = dict(re.findall(r'(\w+)\["([^"]*)"\]', text))
    phases, order_decl, fanout, stack = {}, [], set(), []
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r'subgraph\s+(\w+)\["([^"]*)"\]', line)
        if m:
            sid, slabel = m.group(1), m.group(2)
            if not stack:                       # a top-level subgraph = a phase
                phases[sid] = {"label": slabel, "tasks": []}
                order_decl.append(sid)
            stack.append(sid)
            continue
        if line == "end":
            if stack:
                stack.pop()
            continue
        nm = re.match(r'(\w+)\["[^"]*"\]\s*$', line)   # a leaf task-node declaration
        if nm and stack:
            nid, top = nm.group(1), stack[0]
            if nid != top and nid in node_label:
                phases[top]["tasks"].append(nid)
                if len(stack) > 1:              # inside a nested subgraph → fan-out
                    fanout.add(nid)
        elif nm and not stack:                  # a top-level single-task node = its own phase
            nid = nm.group(1)
            if nid in node_label and nid not in phases:
                phases[nid] = {"label": node_label[nid], "tasks": []}
                order_decl.append(nid)
    succ = {a: b for a, b in re.findall(r'(\w+)\s*==>\s*(\w+)', text) if a in phases and b in phases}
    targets = set(succ.values())
    ordered, seen = [], set()
    for s in [p for p in order_decl if p not in targets] or order_decl:
        cur = s
        while cur and cur not in seen:
            ordered.append(cur); seen.add(cur); cur = succ.get(cur)
    for p in order_decl:
        if p not in seen:
            ordered.append(p); seen.add(p)
    return [(phases[p]["label"], [(t, node_label.get(t, t)) for t in phases[p]["tasks"]]) for p in ordered], fanout


# Session-reporting phases that describe the write-up rather than the science;
# omitted from the workflow diagram so it shows only the research pipeline.
DIAGRAM_OMIT_PHASES = {"summarize", "reflection"}


# Ai2 / Varnish design tokens (assets design system) used to theme the mermaid diagram.
_DZ = {
    "extra_dark_teal": "#032629", "dark_teal": "#0a3235", "teal": "#105257",
    "cream": "#faf2e9", "green": "#0fcb8c", "pink": "#f0529c", "gray60": "#858585",
}

# Optional executing-agent label per phase (the Asta agent that runs that phase's steps);
# phases without an entry (e.g. literature_search, evidence_gathering) get no agent line.
AGENT_BY_PHASE = {
    "auto_discovery": "AutoDiscovery",
    "discovery_run": "AutoDiscovery",
    "literature_search": "Paper Finder",
    "reproduction": "DataVoyager",
    "replication": "DataVoyager",
    "theorizer": "Theorizer",
}

# each executing agent gets its own Ai2/Varnish-branded node colour; phases without an agent
# (e.g. evidence_gathering) fall back to the neutral cream style.
AGENT_CLASS = {
    "AutoDiscovery": "autods", "Paper Finder": "paperfinder",
    "DataVoyager": "datavoyager", "Theorizer": "theorizer",
}


def _mermaid_esc(s):
    """Human-readable label for a mermaid quoted node string: drop quotes/newlines and
    render task/phase ids with spaces instead of underscores."""
    return str(s).replace('"', "'").replace("\n", " ").replace("_", " ").strip()


def flow_diagram(sess, ctx):
    """A compact Quarto `{mermaid}` diagram of the executed workflow, DERIVED from the flow's
    compiled mermaid (.mmd) so it never drifts from the flow definition. Generic across flows;
    themed with the Ai2/Varnish design tokens (assets DESIGN.md). One node per executed phase,
    left-to-right in execution order, each listing its task steps; fan-out phases (branches run
    in parallel) are marked with a ⟳ and a distinct fill."""
    phases, fanout = _parse_flow_mmd(sess.flow)
    phases = [p for p in phases if p[0] not in DIAGRAM_OMIT_PHASES]
    if not phases:
        return ""

    d = _DZ
    nodes, order = [], []
    for i, (plabel, tasks) in enumerate(phases):
        nid = "p%d" % i
        order.append(nid)
        # phase name (strip the mermaid "— fan-out (…)" annotation; encode it as the ⟳ marker)
        name = re.split(r"\s+—\s+", plabel)[0].strip()
        is_fan = any(t[0] in fanout for t in tasks) or "fan-out" in plabel
        # SINGLE-LINE label only: multi-line mermaid labels emit an SVG <foreignObject> (HTML),
        # which rsvg-convert cannot rasterise for the PDF. The node shows the phase name; the
        # executing agent is conveyed by the node colour (see the legend below the diagram).
        agent = AGENT_BY_PHASE.get(name)
        label = _mermaid_esc(name) + (" ⟳" if is_fan else "")
        cls = AGENT_CLASS.get(agent, "neutral")   # colour by executing agent
        nodes.append('  %s["%s"]:::%s' % (nid, label, cls))
    edges = "  " + " --> ".join(order) if len(order) > 1 else ""

    init = (
        "%%%%{init: {'theme':'base',"
        "'flowchart':{'htmlLabels':false,'padding':10,'nodeSpacing':26},"
        "'themeVariables':{"
        # monospace so mermaid's text-width measurement matches the rendered font (else short
        # single-line nodes clip in the png render)
        "'fontFamily':'Courier New, monospace',"
        "'primaryColor':'%s',"          # node fill
        "'primaryTextColor':'%s',"      # node text
        "'primaryBorderColor':'%s',"    # node border
        "'lineColor':'%s'"              # edges
        "}}}%%%%" % (d["cream"], d["extra_dark_teal"], d["teal"], d["pink"])
    )
    body = "\n".join([
        init,
        "flowchart LR",
        *nodes,
        edges,
        # per-agent node colours (Ai2/Varnish tints), + neutral cream for agent-less phases
        "  classDef autods fill:#cbead6,stroke:%s,stroke-width:1.5px,color:%s;"      # green
        % (d["green"], d["extra_dark_teal"]),
        "  classDef paperfinder fill:#d6e4e5,stroke:%s,stroke-width:1.5px,color:%s;" # teal
        % (d["teal"], d["extra_dark_teal"]),
        "  classDef datavoyager fill:#f8d2da,stroke:%s,stroke-width:1.5px,color:%s;" # pink
        % (d["pink"], d["extra_dark_teal"]),
        "  classDef theorizer fill:#d3e6fb,stroke:#2a88ef,stroke-width:1.5px,color:%s;"  # info-blue
        % d["extra_dark_teal"],
        "  classDef neutral fill:%s,stroke:#858585,stroke-width:1.5px,color:%s;"     # cream / gray
        % (d["cream"], d["extra_dark_teal"]),
    ])
    # colour legend (raw LaTeX): swatch colours match the per-agent node fills' borders
    legend = (
        "```{=latex}\n"
        "\\begin{center}\\footnotesize\\sffamily\\color{ai2foreground}"
        "\\textbf{Executing agent:}\\quad"
        "\\textcolor[HTML]{0FCB8C}{$\\blacksquare$}~AutoDiscovery\\quad"
        "\\textcolor[HTML]{105257}{$\\blacksquare$}~Paper Finder\\quad"
        "\\textcolor[HTML]{F0529C}{$\\blacksquare$}~DataVoyager\\quad"
        "\\textcolor[HTML]{2A88EF}{$\\blacksquare$}~Theorizer\\end{center}\n"
        "```\n"
    )
    return (
        "```{mermaid}\n"
        "%%| fig-width: 6.4\n"
        + body + "\n"
        "```\n\n" + legend
    )


def _slug(s):
    return "ent-" + (re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-").lower() or "x")


# coarse fallback: which report section a task type lands in (per-instance subject wins; see compute_anchors)
TASK_SECTION = {
    "literature_search": "#sec-methods", "thematic_search": "#sec-methods",
    "evidence_gathering": "#sec-methods", "cohort_assembly": "#sec-methods",
    "auto_discovery": "#sec-laws", "discovery_run": "#sec-laws",
    "experiment_design": "#sec-laws", "analysis": "#sec-laws", "audit": "#sec-laws",
    "holdout_replication": "#sec-laws",
    "theory_formation": "#sec-theories",
    "novelty_assessment": "#sec-theories",
}


def compute_anchors(sess, ctx, known):
    """The node↔report map the flows-UX uses to scroll the report to a node's section.
    by_issue: a beads issue → its most-specific anchor (per-entity subsection when the
    branch audits a law/theory/hypothesis, else the section). by_task_type: coarse
    fallback for flow nodes with no resolved instance."""
    subj_of = ctx.get("issue_subject", {})
    by_issue = {}
    for i in sess.tasks:
        iid, tt = i["id"], rs(i)["task_type"]
        s = subj_of.get(iid)
        if s and s in known:
            by_issue[iid] = "#" + known[s]
        elif tt in TASK_SECTION:
            by_issue[iid] = TASK_SECTION[tt]
    return {"by_issue": by_issue, "by_task_type": dict(TASK_SECTION)}


# Deep-link URL templates per producing agent. The host is a placeholder until run
# publishing lands; override via CLI (--autods-base / --theorizer-base / --datavoyager-base).
# {run_id} / {task_id} fill deterministically from identifiers in the records.
LINK_TEMPLATES = {
    "autodiscovery": "https://asta.allenai.org/autodiscovery/runs/{run_id}",
    "theorizer": "https://asta.allenai.org/theorizer/tasks/{task_id}",
    "datavoyager": "https://asta.allenai.org/datavoyager/tasks/{task_id}",
}


def build_links(ctx, sess, overrides=None):
    """The cover's deep-link header, built deterministically from identifiers in the
    session: the AutoDiscovery run from run_id, and Theorizer / DataVoyager from their
    A2A task ids when present. An agent with no id (older runs) yields no badge."""
    tmpl = dict(LINK_TEMPLATES)
    tmpl.update(overrides or {})
    links = []
    if ctx.get("run_id") and tmpl.get("autodiscovery"):
        links.append({"label": "AutoDiscovery run", "url": tmpl["autodiscovery"].format(run_id=ctx["run_id"])})
    a2a = {}
    for i in sess.tasks:
        for a in rs(i)["output_json"].get("artifacts") or []:
            m = a.get("metadata") or {}
            ag, tid = m.get("agent"), m.get("a2a_task_id")
            if ag in ("theorizer", "datavoyager") and tid and ag not in a2a and tmpl.get(ag):
                a2a[ag] = tmpl[ag].format(task_id=tid)
    for ag, label in (("theorizer", "Theorizer run"), ("datavoyager", "DataVoyager run")):
        if a2a.get(ag):
            links.append({"label": label, "url": a2a[ag]})
    return links


def build(sess, base_url="", site=False, clickable=True, link_overrides=None):
    """Returns (report_text, anchors). site=True emits the body only (sections + entity
    anchors, no front-matter / TikZ flow / TOC) for embedding in the auto-ds-community run
    page — the workflow graph is that site's right pane. site=False emits the standalone
    branded qmd (front-matter + flow diagram + TOC) for HTML+PDF rendering. clickable=False
    renders the agent-result labels (DataVoyager result, theory store, experiment ids) as
    plain text rather than hyperlinks — a clean, shareable PDF with no links into run files."""
    ctx = collect(sess, base_url)
    ctx["mission"] = mission_intro()
    title = (ctx.get("summary") or {}).get("title") \
        or re.sub(r"^Mission:\s*", "", title_from_mission(sess.epic.get("title", "Research report")))
    subtitle = FLOW_SUBTITLE.get(sess.flow, sess.flow.replace("_", " "))
    # Asta is the author; Allen Institute for AI (added by \postauthor) is the affiliation.
    # The individual agent names are not listed under the title.
    author = "Asta"
    # the index fields are wiki/atlas metadata: carried in the PDF metadata header, not rendered in the body
    _idx = ctx.get("summary") or {}
    keywords = [_idx.get(k) for k in ("discipline", "domain", "topic", "discovery_type") if _idx.get(k)]

    # in-document anchors for every claim id, so id mentions cross-link to their subsection
    known = {x["id"]: _slug(x["id"]) for x in ctx["laws"] + ctx["theories"] if x.get("id")}
    for d in ctx.get("datasets") or []:   # datasets are anchor targets too (for cross-nav chips)
        if d.get("id"):
            known[d["id"]] = _slug(d["id"])

    def anchor(i):
        return known.get(i, _slug(i))

    def ref(i):
        a = known.get(i)
        return f"[{i}](#{a})" if a else str(i)

    # summary citations: a statement cites an AutoDiscovery run / Theorizer / DataVoyager artifact
    # by an id that must exist in this session's artifacts. cite_map holds only those real ids
    # (run_id, a2a_task_id, artifactId -> deep-link), so an id the agent invents resolves to
    # nothing and renders as plain text - no fabricated link ever reaches the reader.
    cite_tmpl = {**LINK_TEMPLATES, **(link_overrides or {})}
    cite_map = {}
    for i in sess.tasks:
        for a in rs(i)["output_json"].get("artifacts") or []:
            m = a.get("metadata") or {}
            ag, url = m.get("agent"), m.get("share_url")
            if not url and ag == "autodiscovery" and m.get("run_id") and cite_tmpl.get("autodiscovery"):
                url = cite_tmpl["autodiscovery"].format(run_id=m["run_id"])
            elif not url and ag in ("theorizer", "datavoyager") and m.get("a2a_task_id") and cite_tmpl.get(ag):
                url = cite_tmpl[ag].format(task_id=m["a2a_task_id"])
            if not url:
                continue
            for key in (a.get("artifactId"), m.get("run_id"), m.get("a2a_task_id")):
                if key:
                    cite_map.setdefault(key, url)
    cite_default = {"autodiscovery_run": "AutoDiscovery run", "theorizer_artifact": "Theorizer", "datavoyager_run": "DataVoyager run"}
    dropped = []

    def _stmt(st):
        st = st or {}
        marks = []
        for c in st.get("citations") or []:
            url = cite_map.get(c.get("ref"))
            label = c.get("label") or cite_default.get(c.get("kind"), "source")
            if url and clickable:
                marks.append(f"[{label}]({url})")
            else:
                marks.append(label)
                if not url and c.get("ref"):
                    dropped.append(c["ref"])
        return st.get("text", "") + (f" ({', '.join(marks)})" if marks else "")

    def prose(x):
        if isinstance(x, dict):                       # a single statement
            return _stmt(x)
        if isinstance(x, list) and x and isinstance(x[0], dict) and "sentences" in x[0]:
            return "\n\n".join(" ".join(_stmt(s) for s in (p.get("sentences") or [])) for p in x)
        if isinstance(x, list):                       # one paragraph: a list of statements
            return " ".join(_stmt(s) for s in x)
        return str(x or "")

    # the executed-workflow diagram is rendered in the Methods section (not the cover), so
    # expose it on ctx for methods.md.j2 to embed.
    ctx["flow_diagram"] = flow_diagram(sess, ctx)

    # the encyclopedia entry (index, context, per-audience executive summaries) is the front matter
    cover = ""
    ctmpl = REPORT_TMPL / "cover.md.j2"
    if ctx.get("summary") and ctmpl.is_file():
        links = build_links(ctx, sess, link_overrides)
        ai2logo = r"\includegraphics[height=16pt]{" + str(LOGO.parent / "logos" / "ai2.pdf").replace("\\", "/") + "}"
        cover = render.render_template_file(ctmpl, ctx=ctx, links=links, flow="",
                                            ai2logo=ai2logo, ref=ref, anchor=anchor, prose=prose,
                                            badge=verdict_badge, tbadge=triage_badge, nbadge=novelty_badge, ntag=novelty_tag, stag=triage_tag, otag=outcome_tag, short=short,
                                            clickable=clickable).strip()
        if dropped:
            print("compile-report: summary cited ids not found in session (rendered as plain text): "
                  + ", ".join(sorted(set(dropped))), file=sys.stderr)

    body = []
    for name in SECTIONS:
        tmpl = REPORT_TMPL / f"{name}.md.j2"
        if not tmpl.is_file():
            continue
        txt = render.render_template_file(tmpl, ctx=ctx, ref=ref, anchor=anchor,
                                          badge=verdict_badge, tbadge=triage_badge, nbadge=novelty_badge, ntag=novelty_tag, stag=triage_tag, otag=outcome_tag, short=short,
                                          clickable=clickable).strip()
        if txt:
            body.append(txt)
    sections = "\n\n".join(body)
    anchors = compute_anchors(sess, ctx, known)

    if site:
        return ((cover + "\n\n") if cover else "") + sections + "\n", anchors

    front = [
        "---",
        f"title: {json.dumps(title)}",
        f"author: {json.dumps(author)}",
        *([("keywords: [" + ", ".join(json.dumps(k) for k in keywords) + "]")] if keywords else []),
        "format:",
        "  pdf:",
        "    documentclass: article",
        "    fontsize: 11pt",
        "    geometry: margin=1in",
        "    toc: false",
        "    number-sections: true",
        "    fig-pos: 'H'",
        "  html:",
        "    toc: true",
        "    theme: cosmo",
        # NB: mermaid-format stays png. SVG output embeds mermaid's <style>-based CSS, which
        # rsvg-convert (the only SVG->PDF converter here) does not apply, dropping all node
        # text; true vector would need Inkscape. png renders text+colour crisply via Chromium.
        "header-includes:",
        "  - |",
        *("    " + ln for ln in header_includes(title)),
        "---",
        "",
        # front block, directly under the title: the one-line intro + the clickable flow
        # diagram (unnumbered — not a body section), then the table of contents, then the
        # numbered body sections. The workflow is thus rendered on the cover/TOC block.
        cover,
        "```{=latex}",
        # TOC lists only the top-level sections (Abstract, Methods, Results, …); the
        # per-hypothesis / per-theory subsections are excluded.
        "\\setcounter{tocdepth}{1}\\vspace{0.5em}\\tableofcontents",
        "```",
    ]
    return "\n".join(front) + "\n\n" + sections + "\n", anchors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="report.qmd")
    ap.add_argument("--render", action="store_true", help="run `quarto render` after writing")
    ap.add_argument("--issues", help="read a beads jsonl export instead of `bd list`")
    ap.add_argument("--base-url", default="",
                    help="absolute prefix for local .asta/ links (for a published report); default relative")
    ap.add_argument("--site", action="store_true",
                    help="emit body-only markdown (no front-matter/flow/TOC) for the auto-ds-community run page")
    ap.add_argument("--anchors", help="write the node↔report anchor map here (default: report_anchors.json beside --out)")
    ap.add_argument("--no-links", action="store_true",
                    help="suppress outbound links into the run's files (a clean, shareable PDF)")
    ap.add_argument("--autods-base", help="URL template for the AutoDiscovery run badge, with {run_id}")
    ap.add_argument("--theorizer-base", help="URL template for the Theorizer run badge, with {task_id}")
    ap.add_argument("--datavoyager-base", help="URL template for the DataVoyager run badge, with {task_id}")
    args = ap.parse_args(argv)

    overrides = {k: v for k, v in (("autodiscovery", args.autods_base),
                                   ("theorizer", args.theorizer_base),
                                   ("datavoyager", args.datavoyager_base)) if v}
    sess = Session(load_issues(args.issues))
    text, anchors = build(sess, args.base_url, args.site, clickable=not args.no_links,
                          link_overrides=overrides or None)
    Path(args.out).write_text(text)
    anchors_path = Path(args.anchors) if args.anchors else Path(args.out).with_name("report_anchors.json")
    anchors_path.write_text(json.dumps(anchors, indent=2) + "\n")
    print(f"compile-report: wrote {args.out} + {anchors_path.name} ({len(sess.tasks)} closed tasks)")

    if args.render:
        try:
            subprocess.run(["quarto", "render", args.out, "--to", "pdf"], check=True)
        except FileNotFoundError:
            sys.exit("compile-report: 'quarto' not found — install Quarto + tinytex to render PDF")
        except subprocess.CalledProcessError:
            sys.exit(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
