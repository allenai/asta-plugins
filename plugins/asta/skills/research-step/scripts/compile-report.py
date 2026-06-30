#!/usr/bin/env python3
"""compile-report.py — render a research session into a publication-quality report.

Deterministic, no LLM. Reads every closed task's typed output_json from beads (or a
jsonl export), joins the primary records by id (laws⨝verdicts⨝audits,
theories⨝novelty⨝triage⨝verdict, hypotheses⨝verdict, provenance, analyses), and
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
SCHEMAS = HERE.parent / "assets" / "schemas.yaml"
REPORT_TMPL = HERE.parent / "assets" / "templates" / "report"
LOGO = HERE.parent / "assets" / "asta-logo.pdf"  # Asta (Ai2) brand mark

sys.path.insert(0, str(HERE))
import render  # noqa: E402

# ordered paper sections (template stem in assets/templates/report/); blank renders skipped
SECTIONS = [
    "mission", "abstract", "methods", "results_laws", "results_theories",
    "results_hypotheses", "trustworthiness", "conclusions",
    "appendix_experiments", "appendix_datasets", "appendix_references",
]

STAGE_LABEL = {
    "cohort_assembly": "Assembled a cohort",
    "provenance_search": "Sourced & acquired data", "provenance_extraction": "Sourced & acquired data",
    "data_acquisition": "Sourced & acquired data", "evidence_gathering": "Sourced & acquired data",
    "data_driven_discovery": "Generated surprising hypotheses from the data",
    "discovery_run": "Generated surprising hypotheses from the data",
    "law_extraction": "Grouped into candidate laws",
    "experiment_design": "Designed prespecified tests", "analysis": "Tested on independent data",
    "audit": "Tested on independent data", "adjudicate": "Reached verdicts",
    "holdout_replication": "Replicated on held-out data",
    "evidence_extraction": "Gathered literature evidence", "theory_formation": "Generated theories",
    "testability_triage": "Triaged testability", "novelty_assessment": "Scored novelty",
    "literature_review": "Surveyed the literature", "hypothesis_formation": "Formed hypotheses",
}

FLOW_SUBTITLE = {
    "data_and_literature_grounded_theory_generation":
        "Reproduction and literature-grounded theory generation over an AutoDiscovery run",
    "auto_discovery": "Cohort assembly, AutoDiscovery, and held-out replication",
    "hypothesis_driven_research": "Literature-driven hypothesis formation and testing",
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
        self.flow = rs(self.epic).get("flow", "")
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


_JOURNALISH = ("journal", "cambridge", "copernicus", "elsevier", "springer", "wiley", "nature publ")


def _is_data_repo(repo):
    """A data archive (RGI/NSIDC/Theia/Zenodo/WGMS/…) vs. a journal/publisher venue."""
    r = (repo or "").lower()
    return bool(r) and not any(w in r for w in _JOURNALISH)


# Figures the producing agent flagged as empty/unrendered — a blank axes with a
# "the plot is empty" caption is noise in a shareable report, so they're dropped.
_EMPTY_FIG_RE = re.compile(r"(?i)\bempty\b|\bunrendered\b|no data|missing data")


def _useful_fig(f):
    return bool(f.get("image")) and not _EMPTY_FIG_RE.search(f.get("caption") or "")


# ---------- join records into a render context ----------

def collect(sess, base_url=""):
    def out(tt):
        return [rs(i)["output_json"] for i in sess.tasks if rs(i)["task_type"] == tt]

    laws, theories, hypotheses = [], [], []
    for tt in ("law_extraction", "discovery_run"):
        for o in out(tt):
            laws += o.get("empirical_laws") or []
    for o in out("theory_formation"):
        store = _art_of_type(o, "theory_store")  # theory cites the store file that formed it
        for t in o.get("theories") or []:
            t["link"] = art_link(store, base_url)
            theories.append(t)
    for o in out("hypothesis_formation"):
        hypotheses += o.get("hypotheses") or []

    evals, triage = {}, {}
    for o in out("novelty_assessment"):
        for e in o.get("theory_evaluations") or []:
            evals[e.get("theory_id")] = e
    for o in out("testability_triage"):
        for a in (o.get("testability_triage") or {}).get("assessments") or []:
            triage[a.get("theory_id")] = a

    verdicts, audits = {}, {}
    for tt in ("adjudicate", "holdout_replication"):
        for o in out(tt):
            a = o.get("adjudication")
            if a and a.get("subject_id"):
                verdicts[a["subject_id"]] = a
    for o in out("audit"):
        ar = o.get("audit_report")
        if ar and ar.get("subject_id"):
            audits[ar["subject_id"]] = ar

    # designs, figures, and the DataVoyager result, associated to a subject via the branch group
    designs, figs, dv, issue_subject = {}, {}, {}, {}
    groups = {}
    for i in sess.tasks:
        groups.setdefault(i["id"].rsplit(".", 1)[0], []).append(i)
    for members in groups.values():
        subj = None
        for m in members:
            o = rs(m)["output_json"]
            if rs(m)["task_type"] in ("adjudicate", "holdout_replication"):
                subj = (o.get("adjudication") or {}).get("subject_id") or subj
            if rs(m)["task_type"] == "experiment_design":
                ed = o.get("experiment_design") or {}
                if ed.get("subject_id"):
                    designs[ed["subject_id"]] = ed
        if subj:
            for m in members:  # every step of this branch points at the subject's report section
                issue_subject[m["id"]] = subj
            for m in members:
                o = rs(m)["output_json"]
                for f in o.get("figures") or []:
                    if _useful_fig(f):
                        figs.setdefault(subj, []).append(f)
                if rs(m)["task_type"] in ("analysis", "holdout_replication"):  # the test that decided the verdict
                    link = art_link(_art_of_type(o, "widget_data_voyager"), base_url,
                                    near=(subj.split("_")[0] if subj else ""))
                    if link and subj not in dv:
                        dv[subj] = link

    def enrich(items):
        for x in items:
            i = x.get("id")
            x["verdict"], x["audit"] = verdicts.get(i), audits.get(i)
            x["design"], x["figs"] = designs.get(i), figs.get(i, [])
            x["eval"], x["triage"] = evals.get(i), triage.get(i)
            if not x.get("link"):  # theories already carry their theory-store link
                x["link"] = dv.get(i)
        return items

    enrich(laws)
    enrich(theories)
    enrich(hypotheses)

    datasets, experiments, citations = {}, [], {}
    data_sources, source_access, acquisitions = [], {}, {}
    for i in sess.tasks:
        o = rs(i)["output_json"]
        for ds in o.get("datasets") or []:
            if ds.get("id"):
                datasets.setdefault(ds["id"], ds)
        experiments += o.get("experiments") or []
        for ds in o.get("data_sources") or []:
            data_sources.append(ds)
        for sa in o.get("source_access") or []:
            source_access[sa.get("data_source_id")] = sa
        for ac in o.get("acquisitions") or []:
            acquisitions[ac.get("data_source_id")] = ac
    for o in out("literature_review"):
        for c in (o.get("literature_review") or {}).get("citations") or []:
            citations.setdefault(c.get("corpus_id") or c.get("id") or c.get("title"), c)

    run_id = ""
    for o in out("cohort_assembly") + out("data_driven_discovery"):
        run_id = (o.get("cohort") or {}).get("run_id", "") or run_id
    datasets = list(datasets.values())
    primary = max(datasets, key=lambda d: d.get("n") or 0) if datasets else None

    # experiments cite the AutoDiscovery run: a per-node file when present, else the run's node table
    run_dir = ""
    for o in out("data_driven_discovery") + out("discovery_run"):
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

    provenance = [{"ds": ds, "access": source_access.get(ds.get("id")),
                   "acq": acquisitions.get(ds.get("id"))} for ds in data_sources]

    # references, segmented Papers / Datasets — resolvable identifiers only, deduped.
    # Papers = source publications + literature citations. Datasets = data archives that
    # were used: registered dataset records (with a DOI), plus source data-repositories
    # (non-journal repository) that were not restricted/not-found.
    def _key(u):
        return re.sub(r"[#?].*$", "", (u or "").rstrip("/"))

    ref_papers, ref_datasets = {}, {}
    for ds in data_sources:
        if ds.get("paper_url") and ds.get("paper_title"):
            ref_papers.setdefault(_key(ds["paper_url"]), {"name": ds["paper_title"], "url": ds["paper_url"]})
    for c in citations.values():
        if c.get("url") and c.get("title"):
            ref_papers.setdefault(_key(c["url"]), {"name": c["title"], "url": c["url"]})

    def add_dataset(name, url):  # only archives with their OWN identifier (not a paper already listed)
        if url and name and _key(url) not in ref_papers:
            ref_datasets.setdefault(_key(url), {"name": name, "url": url})

    for d in datasets:  # registered datasets with a resolvable identifier
        url = _doi_url(d.get("source"))
        name = ((d.get("source") or "").split(",")[0].split(" doi")[0].split(";")[0].strip()
                or (d.get("definition") or "").split(":")[0].strip() or d.get("id"))
        add_dataset(name[:90], url)
    for ds in data_sources:  # source data-repositories actually available (not a journal, not restricted)
        sa, ac = source_access.get(ds.get("id")), acquisitions.get(ds.get("id"))
        if not sa or not _is_data_repo(sa.get("repository")):
            continue
        if ac and ac.get("access_status") in ("restricted", "not_found"):
            continue
        add_dataset(ds.get("paper_title") or sa.get("repository"), _doi_url(sa.get("identifier")))

    # overview/summary figures (recursive scan), mapped to a section by producing task
    def find_figs(o):
        f = []
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "figures" and isinstance(v, list):
                    f += [x for x in v if isinstance(x, dict) and _useful_fig(x)]
                else:
                    f += find_figs(v)
        elif isinstance(o, list):
            for v in o:
                f += find_figs(v)
        return f

    overview = {}
    # only summary figures worth a section overview; per-law/theory plots carry the laws
    fig_section = {"theory_synthesis": "theories", "final_synthesis": "theories",
                   "verification_synthesis": "verification"}
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

    summary = next((rs(i)["output_json"].get("summary")
                    for i in sess.tasks if rs(i)["task_type"] == "summarize"), None)

    return {
        "flow": sess.flow,
        "summary": summary,
        "task_types": {rs(i)["task_type"] for i in sess.tasks},
        "laws": laws, "theories": theories, "hypotheses": hypotheses,
        "law_stats": tally(laws), "theory_stats": tally(theories), "hyp_stats": tally(hypotheses),
        "n_theories": len(theories),
        "objectives": sorted({t.get("objective") for t in theories if t.get("objective")}),
        "verified_theories": verified,
        "theories_ordered": verified + [t for t in theories if not t.get("verdict")],
        "held_law_ids": ids_where(laws, lambda v: v.get("outcome") == "held"),
        "held_theory_ids": ids_where(theories, lambda v: v.get("outcome") == "held"),
        "definitional_ids": definitional,
        "ref_papers": list(ref_papers.values()), "ref_datasets": list(ref_datasets.values()),
        "issue_subject": issue_subject,
        "overview": overview,
        "datasets": datasets, "experiments": experiments, "citations": list(citations.values()),
        "provenance": provenance,
        "acquired": sum(1 for p in provenance if (p["acq"] or {}).get("access_status") == "acquired"),
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
    if {"data_driven_discovery", "discovery_run", "cohort_assembly"} & tt:
        used.add("AutoDiscovery")
    if {"analysis", "holdout_replication"} & tt:
        used.add("DataVoyager")
    if {"theory_formation", "evidence_extraction", "novelty_assessment"} & tt:
        used.add("Theorizer")
    if {"literature_review", "provenance_search"} & tt:
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
        # Ai2 palette (ai2style/ai2.cls)
        r"\definecolor{ai2pink}{HTML}{F0529C}",
        r"\definecolor{ai2accent}{HTML}{407579}",
        r"\definecolor{ai2foreground}{HTML}{1C2B33}",
        r"\definecolor{ai2background}{HTML}{FAF2E9}",
        r"\definecolor{ai2dark}{HTML}{0A2B35}",
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
        r"\preauthor{\begin{flushleft}\normalsize\sffamily\color{ai2foreground}}",
        r"\postauthor{\par\end{flushleft}}",
        r"\predate{}\postdate{}\date{}",
        r"\usepackage{graphicx}",
        r"\usepackage{tikz}",
        r"\usetikzlibrary{arrows.meta,positioning}",
        r"\renewcommand{\contentsname}{Contents}",
        r"\usepackage{fancyhdr}",
        r"\newcommand{\astalogo}{\raisebox{-2.5pt}{\includegraphics[height=11pt]{" + logo + r"}}}",
        r"\renewcommand{\headrule}{\hbox to\headwidth{\color{ai2pink}\leaders\hrule height 1pt\hfill}}",
        r"\pagestyle{fancy}\fancyhf{}",
        r"\fancyhead[L]{\astalogo}",
        r"\fancyhead[R]{\small\itshape\color{ai2dark}" + short + "}",
        r"\fancyfoot[L]{\footnotesize\color{gray}Generated by Asta · Allen Institute for AI}",
        r"\fancyfoot[R]{\footnotesize\color{gray}\thepage}",
        r"\fancypagestyle{plain}{\fancyhf{}\fancyhead[L]{\astalogo}"
        r"\fancyfoot[R]{\footnotesize\color{gray}\thepage}"
        r"\renewcommand{\headrule}{\hbox to\headwidth{\color{ai2pink}\leaders\hrule height 1pt\hfill}}}",
        # fill pages instead of leaving big ragged gaps; gentle widow/orphan control
        r"\setlength{\parindent}{0pt}\setlength{\parskip}{0.6em}",
        r"\flushbottom\widowpenalty=1000\clubpenalty=1000",
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


def exec_phases(ctx):
    """The executed workflow as ordered phases (title, detail, Asta agent), built from
    what actually ran; counts come from the joined records."""
    tt = ctx["task_types"]
    has = lambda *xs: any(x in tt for x in xs)
    L, T, H = ctx["law_stats"], ctx["theory_stats"], ctx["hyp_stats"]
    ph = []
    if has("literature_review"):
        ph.append(("Literature review", "survey and gaps", "Paper Finder"))
    if has("provenance_search", "provenance_extraction", "data_acquisition", "evidence_gathering", "cohort_assembly"):
        ph.append(("Data provenance", f"{ctx['acquired']}/{len(ctx['provenance'])} sources", "Paper Finder"))
    if has("data_driven_discovery", "discovery_run"):
        ph.append(("AutoDiscovery", f"{len(ctx['experiments'])} experiments", "AutoDiscovery"))
    if L["n"]:
        # "laws" are the high-surprise hypotheses surfaced by discovery and retained —
        # label them as such in the diagram so the framing is explicit (reviewer note).
        ph.append(("Reproduction", f"{L['n']} high-surprise hypotheses · {L['held']} held", "DataVoyager"))
    if has("theory_formation"):
        ph.append(("Theorizing", f"{ctx['n_theories']} theories", "Theorizer"))
    if T["tested"]:
        ph.append(("Verification", f"{T['tested']} tested · {T['held']} held", "DataVoyager"))
    if has("hypothesis_formation"):
        ph.append(("Hypotheses", f"{H['n']} formed · {H['held']} held", "DataVoyager"))
    return ph


def flow_diagram(sess, ctx):
    """Asta-branded TikZ diagram of the executed workflow (native LaTeX — no headless
    browser, unlike a {mermaid} block, and fully brand-colorable)."""
    phases = exec_phases(ctx)
    if not phases:
        return ""
    nodes = []
    for i, (title, detail, agent) in enumerate(phases):
        body = r"\textbf{%s}" % _tex(title)
        if detail:
            body += r"\\[1pt]{\footnotesize %s}" % _tex(detail)
        if agent:
            body += r"\\[2pt]{\scriptsize\itshape\color{ai2accent}%s}" % _tex(agent)
        pos = "" if i == 0 else (", right=0.45cm of n%d" % (i - 1))
        nodes.append(r"\node[phase%s] (n%d) {%s};" % (pos, i, body))
    arrows = [r"\draw[arr] (n%d) -- (n%d);" % (i, i + 1) for i in range(len(phases) - 1)]
    return (
        "```{=latex}\n"
        "\\begin{center}\n"
        "{\\small\\itshape\\sffamily\\color{ai2foreground}Executed workflow}\\\\[5pt]\n"
        "\\resizebox{\\textwidth}{!}{%\n"
        "\\begin{tikzpicture}[\n"
        "  phase/.style={draw=ai2accent, line width=0.9pt, rounded corners=4pt, fill=white,"
        " text=ai2foreground, align=center, minimum width=2.6cm, inner sep=7pt, minimum height=1.5cm},\n"
        "  arr/.style={-{Stealth[length=2.4mm]}, draw=ai2pink, line width=1.4pt}]\n"
        + "\n".join(nodes + arrows) + "\n"
        "\\end{tikzpicture}}\n"
        "\\end{center}\n"
        "```\n"
    )


def _slug(s):
    return "ent-" + (re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-").lower() or "x")


# coarse fallback: which report section a task type lands in (per-instance subject wins; see compute_anchors)
TASK_SECTION = {
    "literature_review": "#sec-methods", "provenance_search": "#sec-methods",
    "provenance_extraction": "#sec-methods", "data_acquisition": "#sec-methods",
    "evidence_gathering": "#sec-methods", "cohort_assembly": "#sec-methods",
    "data_driven_discovery": "#sec-laws", "discovery_run": "#sec-laws", "law_extraction": "#sec-laws",
    "experiment_design": "#sec-laws", "analysis": "#sec-laws", "audit": "#sec-laws",
    "adjudicate": "#sec-laws", "holdout_replication": "#sec-laws",
    "evidence_extraction": "#sec-theories", "theory_formation": "#sec-theories",
    "testability_triage": "#sec-theories", "novelty_assessment": "#sec-theories",
    "hypothesis_formation": "#sec-hypotheses",
}


def compute_anchors(sess, ctx, known):
    """The node↔report map the flows-UX uses to scroll the report to a node's section.
    by_issue: a beads issue → its most-specific anchor (per-entity subsection when the
    branch adjudicates a law/theory/hypothesis, else the section). by_task_type: coarse
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


def build(sess, base_url="", site=False, clickable=True):
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

    # in-document anchors for every claim id, so id mentions cross-link to their subsection
    known = {x["id"]: _slug(x["id"]) for x in ctx["laws"] + ctx["theories"] + ctx["hypotheses"] if x.get("id")}

    def anchor(i):
        return known.get(i, _slug(i))

    def ref(i):
        a = known.get(i)
        return f"[{i}](#{a})" if a else str(i)

    # the encyclopedia entry (index, context, per-audience executive summaries) is the front matter
    cover = ""
    ctmpl = REPORT_TMPL / "cover.md.j2"
    if ctx.get("summary") and ctmpl.is_file():
        cover = render.render_template_file(ctmpl, ctx=ctx, ref=ref, anchor=anchor, clickable=clickable).strip()

    body = []
    for name in SECTIONS:
        tmpl = REPORT_TMPL / f"{name}.md.j2"
        if not tmpl.is_file():
            continue
        txt = render.render_template_file(tmpl, ctx=ctx, ref=ref, anchor=anchor, clickable=clickable).strip()
        if txt:
            body.append(txt)
    sections = "\n\n".join(body)
    anchors = compute_anchors(sess, ctx, known)

    if site:
        return ((cover + "\n\n") if cover else "") + sections + "\n", anchors

    front = [
        "---",
        f"title: {json.dumps(title)}",
        f"subtitle: {json.dumps(subtitle)}",
        'author: "Asta · Allen Institute for AI"',
        "format:",
        "  pdf:",
        "    documentclass: article",
        "    fontsize: 11pt",
        "    geometry: margin=1in",
        "    toc: false",
        "    number-sections: true",
        "  html:",
        "    toc: true",
        "    theme: cosmo",
        "header-includes:",
        "  - |",
        *("    " + ln for ln in header_includes(title)),
        "---",
        "",
        cover,
        flow_diagram(sess, ctx),
        "```{=latex}",
        "\\vspace{0.5em}\\tableofcontents",
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
    args = ap.parse_args(argv)

    sess = Session(load_issues(args.issues))
    text, anchors = build(sess, args.base_url, args.site, clickable=not args.no_links)
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
