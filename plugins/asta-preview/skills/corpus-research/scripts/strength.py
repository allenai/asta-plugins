"""strength.py — [T] strength-v1: per-side evidence-strength profiles over stance rows.

strength-v1 is a DECLARED, VERSIONED VIEW composed from fields extraction already ships —
nothing new is invented at extraction time (the strength-v1 view, deliverables.md §disagreement; the un-deferred
source-trust-v0 slice). Inputs per stance/evidence row:
  fit                 explicit | rephrased | reframed | stretch | legacy-unwarranted
  basis.source_tier   fulltext | abstract | snippet
  stratum             S1 peer-reviewed | S2 preprint | S3 non-indexed        (optional)
  validation          validated-isolated | validated-endtoend | described | proposed
                      (optional; only present where the claim is method-shaped)
  basis.support_kind  OPEN vocabulary (suggested: own-experiment · own-ablation ·
                      benchmark-result · qualitative-analysis · theoretical-argument ·
                      citation-to-other-work · position-assertion · "other: <specific>") —
                      counted verbatim, never validated against a closed list (the strength-note convention)
  citationCount       external context label from existing metadata               (optional)

THE PREDICATE (v1 — changing it is a NEW VERSION, never a silent edit):
  strong  <=>  fit in {explicit, rephrased}
          AND  source_tier == fulltext
          AND  (validation in {validated-isolated, validated-endtoend} IF the row carries a
                validation field; a row with NO validation field carries no validation
                requirement — most claims are not method-shaped)
GUARDRAILS (user-ruled):
  * STRATUM NEVER DISQUALIFIES — venue prestige is not strength; the not-yet-popular good
    work is often S2 preprints. Stratum (and citations, and support_kind) appear in the
    profile as SLICE/CONTEXT LABELS ONLY, deliberately absent from the predicate.
  * NO mechanical score aggregation (the strength-note convention): strength-v1 + the support-kind mix are INPUTS
    the synthesis judge weighs; the weighing itself is recorded in because/unless.

Output: per-(axis, side) profile — the per-side strength profile every shipped axis record
must carry (report_gate check 11):
  {n, n_papers, strong, strong_papers, strong_share, floor_met,
   by_fit, by_tier, by_stratum, by_validation, by_support_kind (all row counts;
   missing fields count under "unrecorded", never fail — legacy rows are normal),
   citations_median ("unrecorded" when no metadata reaches the rows),
   strength_note_missing (rows carrying support_kind but no strength_note — the
   always-written nuance carrier, the strength-note convention)}
The support gate's quality floor reads "floor_met: strong_papers >= --floor" (default 2)
instead of quote-counting. Share never gates inclusion — it only classifies.

Usage:
  python strength.py <stance-rows.jsonl> [--axis-field axis] [--side-field stance]
                     [--floor 2] [--meta <candidates.jsonl>] [--out <data/strength.json>]
--meta joins citationCount (and stratum, if present) by corpusId from a metadata file.
Rows missing axis/side fields are COUNTED and reported, never fatal (schema variance is
normal). Exit 0 always — this is a view computer; gates consume its output.
"""
from __future__ import annotations
import json, os, re, statistics, sys
from collections import Counter

VERSION = "strength-v1"
STRONG_FIT = ("explicit", "rephrased")
STRONG_TIER = "fulltext"
STRONG_VALIDATION = ("validated-isolated", "validated-endtoend")
PREDICATE = ("strong = fit in (explicit, rephrased) AND source_tier == fulltext AND "
             "(validation in (validated-isolated, validated-endtoend) when a validation "
             "field exists, else no validation requirement); stratum/citations/support_kind "
             "are labels, NEVER disqualifiers")


def _field(row, *names):
    """First non-empty string among names, looked up on the row then its basis dict —
    schema-tolerant (field homes vary by round/thread); normalized lowercase-hyphenated."""
    basis = row.get("basis") if isinstance(row.get("basis"), dict) else {}
    for n in names:
        for src in (row, basis):
            v = src.get(n)
            if isinstance(v, str) and v.strip():
                return re.sub(r"[\s_]+", "-", v.strip().lower())
    return None


def row_fields(row):
    """(fit, tier, stratum, validation, support_kind, citations) for one row — every
    optional absence stays None here; profiles render it 'unrecorded'."""
    fit = _field(row, "fit") or "legacy-unwarranted"
    tier = _field(row, "source_tier", "text_source", "evidence_depth", "tier")
    if tier and "full" in tier:
        tier = "fulltext"                      # full-text / full_text dialects
    stratum = _field(row, "stratum", "source_stratum", "trust_stratum")
    if stratum and re.fullmatch(r"s\d", stratum):
        stratum = stratum.upper()              # the v0 ladder labels are S1/S2/S3
    validation = _field(row, "validation", "validation_grade", "validation_status",
                        "validated")
    sk = None                                   # OPEN vocabulary — verbatim, never enum-checked
    basis = row.get("basis") if isinstance(row.get("basis"), dict) else {}
    for src in (basis, row):
        v = src.get("support_kind")
        if isinstance(v, str) and v.strip():
            sk = re.sub(r"\s+", " ", v.strip().lower())
            break
    cites = None
    for k in ("citationCount", "citation_count", "citations", "n_citations"):
        for src in (row, basis):
            v = src.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cites = int(v)
                break
        if cites is not None:
            break
    return fit, tier, stratum, validation, sk, cites


def strength_v1(fit, source_tier, validation=None):
    """THE predicate (see module docstring). validation=None = no validation field on the
    row = no validation requirement. Stratum is deliberately not a parameter."""
    return (fit in STRONG_FIT and source_tier == STRONG_TIER
            and (validation is None or validation in STRONG_VALIDATION))


def _note_missing(row):
    """A row carrying support_kind must carry a non-empty strength_note (the strength-note convention)."""
    basis = row.get("basis") if isinstance(row.get("basis"), dict) else {}
    if not any(isinstance(s.get("support_kind"), str) and s["support_kind"].strip()
               for s in (row, basis)):
        return False                            # legacy row — no requirement
    return not any(isinstance(s.get("strength_note"), str) and s["strength_note"].strip()
                   for s in (row, basis))


def profiles(rows, axis_field="axis", side_field="stance", floor=2, meta=None):
    """rows -> {"axes": {axis: {side: profile}}, ...counters}. Rows without an axis or side
    are counted (skipped_no_axis_side), never fatal. meta = {corpusId: row} join for
    citationCount/stratum context labels (existing metadata only — zero extraction cost)."""
    meta = meta or {}
    axes, skipped = {}, 0
    for row in rows:
        axis = row.get(axis_field) or row.get("axis")
        side = (row.get(side_field) or row.get("stance") or row.get("side")
                or row.get("position"))
        if not (isinstance(axis, str) and axis.strip()
                and isinstance(side, str) and side.strip()):
            skipped += 1
            continue
        cid = row.get("corpusId", row.get("corpus_id", row.get("paperId")))
        cid = str(cid) if cid is not None else None
        mrow = meta.get(cid, {}) if cid else {}
        joined = dict(mrow, **row) if mrow else row
        fit, tier, stratum, validation, sk, cites = row_fields(joined)
        strong = strength_v1(fit, tier, validation)
        b = axes.setdefault(axis.strip(), {}).setdefault(side.strip(), {
            "rows": [], "papers": set(), "strong_papers": set()})
        b["rows"].append((fit, tier, stratum, validation, sk, cites, strong,
                          _note_missing(joined)))
        if cid:
            b["papers"].add(cid)
            if strong:
                b["strong_papers"].add(cid)
    out = {}
    for axis, sides in sorted(axes.items()):
        out[axis] = {}
        for side, b in sorted(sides.items()):
            rs = b["rows"]
            cnt = lambda i: dict(Counter((r[i] or "unrecorded") for r in rs))
            cites = [r[5] for r in rs if r[5] is not None]
            strong_papers = (len(b["strong_papers"]) if b["papers"]
                             else sum(1 for r in rs if r[6]))
            out[axis][side] = {
                "n": len(rs), "n_papers": len(b["papers"]) or len(rs),
                "strong": sum(1 for r in rs if r[6]),
                "strong_papers": strong_papers,
                "strong_share": round(sum(1 for r in rs if r[6]) / len(rs), 3),
                "floor_met": strong_papers >= floor,
                "by_fit": cnt(0), "by_tier": cnt(1), "by_stratum": cnt(2),
                "by_validation": cnt(3), "by_support_kind": cnt(4),
                "citations_median": (int(statistics.median(cites)) if cites
                                     else "unrecorded"),
                "strength_note_missing": sum(1 for r in rs if r[7]),
            }
    return out, skipped


def _read_rows(path):
    rows, bad = [], 0
    for line in open(path, errors="replace"):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            assert isinstance(r, dict)
            rows.append(r)
        except Exception:
            bad += 1
    return rows, bad


def _read_meta(path):
    meta = {}
    for row in _read_rows(path)[0]:
        cid = row.get("corpusId", row.get("corpus_id", row.get("paperId")))
        if cid is not None:
            meta[str(cid)] = row
    return meta


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    opt = lambda flag, default, cast=str: (cast(args[args.index(flag) + 1])
                                           if flag in args else default)
    src = args[0]
    if not os.path.isfile(src):
        raise SystemExit(f"{src}: not found — pass a stance-rows jsonl "
                         f"(one row per {{axis, stance, quote, fit, basis}} claim)")
    rows, bad = _read_rows(src)
    meta_path = opt("--meta", None)
    meta = _read_meta(meta_path) if meta_path else {}
    floor = opt("--floor", 2, int)
    ax, skipped = profiles(rows, axis_field=opt("--axis-field", "axis"),
                           side_field=opt("--side-field", "stance"),
                           floor=floor, meta=meta)
    result = {"version": VERSION, "predicate": PREDICATE, "floor": floor,
              "source": src, "rows_read": len(rows), "bad_json_lines": bad,
              "skipped_no_axis_side": skipped,
              "meta_joined": len(meta) if meta else 0,
              "view": "strength-v1",
              "predicate": "strong = fit in (explicit, rephrased) AND tier == fulltext "
                           "AND (validation in validated-* when the field exists); "
                           "stratum/citations/support_kind are labels, never parameters",
              "axes": ax}
    out = opt("--out", None)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        json.dump(result, open(out, "w"), indent=1, ensure_ascii=False)
        print(f"wrote {out}: {len(ax)} axes")
    print(json.dumps(result, indent=1, ensure_ascii=False))
    if not ax and rows:
        print(f"NOTE: 0 axes from {len(rows)} rows ({skipped} rows lacked axis/side "
              f"fields) — name them with --axis-field/--side-field if this file uses "
              f"different keys", file=sys.stderr)
