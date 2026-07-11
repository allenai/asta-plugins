"""vault.py — [T] build and grow a corpus thread's VAULT (see references/vault.md).

The growth model this enforces (the vault's whole integrity story):
  canonical rounds/<id>/ are APPEND-ONLY (folded verbatim, never edited);
  caches merge append-only (fetch-once; existing files win);
  view/union.jsonl + vault.json are DERIVED — never hand-edited, always rebuilt here.
Rebuild is deterministic: same rounds in, same view out — a round runs it as its CLOSING
contract step; there is no human maintainer in the loop.

Usage:
  python vault.py init <workspace> --from <run_dir> [--id <round_id>]
      create <workspace>/vault/ with <run_dir> folded in as the founding round.
  python vault.py rebuild <workspace>
      fold any NEW <workspace>/round-*/ dirs (not yet in vault.json's registry) into
      vault/rounds/, merge their caches, and re-derive view/union.jsonl + vault.json.

Round discovery is by REGISTRY, not by name or mtime: a workspace round dir is new iff its
realpath is not recorded as a source in vault.json. New rounds are prepended (newest first =
column order and metadata precedence in the union view).
"""
from __future__ import annotations
import json, os, re, shutil, sys
from collections import Counter

POS = ("in", "relevant")
# a round's canonical record is its WHOLE dir, verbatim — no filename enumeration (an
# earlier enum-based fold silently dropped rounds' living-axes docs and view deltas).
# Excluded: caches (merged separately into vault/cache/), PDFs, files > SIZE_CAP.
CACHE_DIRS = ("fulltext-cache", "s2-cache")
SIZE_CAP = 5_000_000
OBS_SOURCES = ("observations.jsonl", "observations-v1.jsonl", "view-delta.jsonl")


def _jl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def _fold_round(vault, rid, src):
    """Copy a round's canonical record VERBATIM into vault/rounds/<rid>/ (append-only:
    refuses to overwrite an existing round id)."""
    rdir = f"{vault}/rounds/{rid}"
    if os.path.isdir(rdir):
        raise SystemExit(f"rounds/{rid} already exists — canonical records are append-only "
                         f"(pick a new id; never rewrite a prior round)")
    os.makedirs(rdir)
    copied = []
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in CACHE_DIRS and not d.startswith(".")]
        rel = os.path.relpath(base, src)
        for f in files:
            p = os.path.join(base, f)
            if f.endswith(".pdf") or f.startswith(".") or os.path.getsize(p) > SIZE_CAP:
                continue
            dst = os.path.join(rdir, rel, f) if rel != "." else os.path.join(rdir, f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(p, dst)
            copied.append(os.path.relpath(dst, rdir))
    # caches merge append-only: existing vault copy wins (fetch-once, first capture kept)
    for cache in CACHE_DIRS:
        sdir = f"{src}/{cache}"
        if os.path.isdir(sdir):
            cdir = f"{vault}/cache/{cache}"
            os.makedirs(cdir, exist_ok=True)
            for f in os.listdir(sdir):
                if not os.path.exists(f"{cdir}/{f}"):
                    shutil.copy(f"{sdir}/{f}", f"{cdir}/{f}")
    as_of = None
    mp = f"{src}/round-manifest.json"
    if os.path.isfile(mp):
        try:
            as_of = json.load(open(mp)).get("as_of")
        except Exception:
            pass
    return {"id": rid, "source": os.path.realpath(src), "as_of": as_of,
            "judged": 0, "files": copied}


def _derive_aliases(obs_by_round):
    """Thread-side duplicate-id detection: same normalized title under 2+ corpusIds —
    mechanical and auditable; the vault needs no external id knowledge."""
    tid = {}
    for obs in obs_by_round.values():
        for cid, r in obs.items():
            t = re.sub(r"[^a-z0-9]", "", (r.get("title") or "").lower())
            if t:
                tid.setdefault(t, set()).add(cid)
    alias = {}
    for t, ids in tid.items():
        if len(ids) > 1:
            keep = min(ids)
            for c in ids:
                if c != keep:
                    alias[c] = keep
    return alias


def _derive(vault, rounds):
    """Re-derive view/union.jsonl + layer stats from vault/rounds/* — the only writer of
    derived layers. Round order = registry order (newest first): column order + obs precedence."""
    tiers_by_round, obs_by_round = {}, {}
    for r in rounds:
        rdir = f"{vault}/rounds/{r['id']}"
        rel_p = f"{rdir}/standardized-relevance.jsonl"
        rel = {str(x["corpusId"]): x.get("tier") for x in _jl(rel_p)} if os.path.isfile(rel_p) else {}
        obs = {}
        for cand in OBS_SOURCES:
            if os.path.isfile(f"{rdir}/{cand}"):
                obs = {str(x["corpusId"]): x for x in _jl(f"{rdir}/{cand}")}
                break
        tiers_by_round[r["id"]], obs_by_round[r["id"]] = rel, obs
        r["judged"] = len(rel)
    alias = _derive_aliases(obs_by_round)
    A = lambda c: alias.get(c, c)
    tiers_by_round = {rid: {A(c): t for c, t in rel.items()} for rid, rel in tiers_by_round.items()}
    obs_by_round = {rid: {A(c): x for c, x in o.items()} for rid, o in obs_by_round.items()}
    all_ids = set()
    for rel in tiers_by_round.values():
        all_ids |= set(rel)
    rows = []
    for cid in sorted(all_ids):
        tiers = {rid: tiers_by_round[rid][cid] for rid in tiers_by_round
                 if cid in tiers_by_round[rid]}
        judged = [t for t in tiers.values() if t]
        pos = [t in POS for t in judged]
        agreement = ("agreed-positive" if judged and all(pos) else
                     "agreed-negative" if judged and not any(pos) else
                     "DISPUTED" if judged else "unjudged")
        o = next((obs_by_round[r][cid] for r in obs_by_round if cid in obs_by_round[r]), {})
        rows.append({"corpusId": cid, "title": o.get("title"), "year": o.get("year"),
                     "tiers_by_round": tiers, "n_rounds_judged": len(judged),
                     "agreement": agreement,
                     "trust": f"{agreement}/{len(judged)}x",
                     "primary_family_latest": o.get("primary_family") or o.get("primary_family_latest")})
    os.makedirs(f"{vault}/view", exist_ok=True)
    with open(f"{vault}/view/union.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    layers = {"aliases": {"pairs": len(alias), "map": alias},
              "view": {"rows": len(rows),
                       "agreement": dict(Counter(r["agreement"] for r in rows)),
                       "judged_by_n_rounds": dict(sorted(Counter(
                           r["n_rounds_judged"] for r in rows).items()))}}
    for cache in ("fulltext-cache", "s2-cache"):
        cdir = f"{vault}/cache/{cache}"
        layers[cache] = {"files": len(os.listdir(cdir)) if os.path.isdir(cdir) else 0}
    return layers


def rebuild(workspace):
    vault = f"{workspace}/vault"
    vj = f"{vault}/vault.json"
    meta = json.load(open(vj)) if os.path.isfile(vj) else {"rounds": [], "layers": {}}
    # identity must survive a moved/copied workspace: match id, recorded path, OR the
    # recorded source's basename (a copied workspace re-folding its own rounds = 2x rows)
    known = ({r.get("source") for r in meta["rounds"]} | {r["id"] for r in meta["rounds"]}
             | {os.path.basename(r["source"]) for r in meta["rounds"] if r.get("source")})
    new = []
    for d in sorted(os.listdir(workspace), reverse=True):  # newest round number first
        p = f"{workspace}/{d}"
        # a closable round has at least a round-manifest; rows-less rounds (pure
        # consolidation/audit) still fold — their manifests + trust-upgrades are vault knowledge
        if (re.fullmatch(r"round-[\w.-]+", d) and os.path.isdir(p)
                and os.path.realpath(p) not in known and d not in known
                and (os.path.isfile(f"{p}/round-manifest.json")
                     or os.path.isfile(f"{p}/standardized-relevance.jsonl"))):
            new.append((d, p))
    for rid, src in new:
        meta["rounds"].insert(0, _fold_round(vault, rid, src))
        print(f"folded {rid} <- {src}")
    meta["layers"] = _derive(vault, meta["rounds"])
    json.dump(meta, open(vj, "w"), indent=1)
    return meta


def init(workspace, run_dir, rid="r1"):
    vault = f"{workspace}/vault"
    if os.path.isdir(f"{vault}/rounds"):
        raise SystemExit(f"{vault} already initialized — use rebuild")
    os.makedirs(vault, exist_ok=True)
    meta = {"rounds": [_fold_round(vault, rid, run_dir)], "layers": {}}
    meta["layers"] = _derive(vault, meta["rounds"])
    json.dump(meta, open(f"{vault}/vault.json", "w"), indent=1)
    open(f"{vault}/QUESTIONS.log", "a").close()
    with open(f"{vault}/VAULT-MANIFEST.template.md", "w") as f:
        f.write("# VAULT — <topic>\n<instantiate from references/vault.md template; "
                "counts live in vault.json, don't copy them into prose>\n")
    return meta


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "rebuild":
        m = rebuild(sys.argv[2])
    elif cmd == "init":
        src = sys.argv[sys.argv.index("--from") + 1]
        rid = sys.argv[sys.argv.index("--id") + 1] if "--id" in sys.argv else "r1"
        m = init(sys.argv[2], src, rid)
    else:
        raise SystemExit(__doc__)
    print(json.dumps(m["layers"]["view"], indent=1))
    for r in m["rounds"]:
        print(f"  {r['id']}: {r['judged']} judged · as-of {r.get('as_of')}")
