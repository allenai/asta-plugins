"""shards.py — [T] shard builder + salt scorer for fan-out worker fleets (see workers.md).

Encodes the three structural fixes measured runs kept missing:
  stratified-interleave assignment (shards exchangeable -> drift is measurable),
  salt items (known-gold planted per shard -> per-judge calibration),
  k-chunked sub-batches (the emission protocol the buffering attractor can't defeat).

Usage:
  from shards import build_shards, score_salt
  build_shards(items, run_dir, n_shards=10, salt=salt_items, k=25,
               strata_key=lambda r: r.get("provenance", ["?"])[0])
      -> writes <run>/judge-input/shard-NN.jsonl (items carry no salt marking),
         <run>/judge-input/salts.json ({shard: [corpusIds]}, keep OUT of worker context),
         sub-batch markers every k items ({"subbatch": m, "emit_now": true} sentinel rows).
  score_salt(judgment_files_glob, salts_path, gold_tiers)
      -> per-shard: salt agreement, strictness delta, boundary calls; flags shards for re-judge.

CLI:  python shards.py score '<run>/judgments/*.jsonl' <run>/judge-input/salts.json gold.json
"""
from __future__ import annotations
import glob, json, os, random

POS = ("in", "relevant")


def _jl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def build_shards(items, run_dir, n_shards=10, salt=None, k=25, strata_key=None, seed=13):
    """items: list of candidate dicts (must carry corpusId). salt: list of dicts with
    corpusId + a `salt_tier` field (the known gold tier) — salt_tier is STRIPPED from the
    written shard rows and recorded only in salts.json."""
    rng = random.Random(seed)
    strata_key = strata_key or (lambda r: "all")
    # stratified interleave: shuffle within stratum, deal round-robin across shards
    strata = {}
    for it in items:
        strata.setdefault(str(strata_key(it)), []).append(it)
    shards = [[] for _ in range(n_shards)]
    i = 0
    for key in sorted(strata):
        rows = strata[key]
        rng.shuffle(rows)
        for r in rows:
            shards[i % n_shards].append(r)
            i += 1
    # salt: distribute a copy of each salt item to every shard? No — ~5 DISTINCT per shard,
    # sampled with replacement across shards so each judge sees a comparable mini-panel.
    salts_map = {}
    if salt:
        for si, sh in enumerate(shards):
            picks = rng.sample(salt, min(5, len(salt)))
            for p in picks:
                row = {kk: v for kk, v in p.items() if kk != "salt_tier"}
                sh.insert(rng.randrange(len(sh) + 1), row)
            salts_map[f"shard-{si:02d}"] = {str(p["corpusId"]): p["salt_tier"] for p in picks}
    outdir = os.path.join(run_dir, "judge-input")
    os.makedirs(outdir, exist_ok=True)
    for si, sh in enumerate(shards):
        with open(f"{outdir}/shard-{si:02d}.jsonl", "w") as f:
            for j, r in enumerate(sh):
                if j and j % k == 0:
                    f.write(json.dumps({"subbatch_boundary": j // k,
                                        "emit_now": "APPEND your judgments for the sub-batch "
                                                    "above BEFORE reading further"}) + "\n")
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(f"{outdir}/salts.json", "w") as f:
        json.dump(salts_map, f, indent=1)
    return outdir, salts_map


def score_salt(judgment_glob, salts_path, gold_tiers=None):
    """Per-shard judge calibration from the planted items. gold_tiers optional override:
    {corpusId: tier}; default = salt_tier recorded in salts.json."""
    salts = json.load(open(salts_path))
    report = {}
    for p in sorted(glob.glob(judgment_glob)):
        shard = os.path.basename(p).split(".")[0]
        key = next((k for k in salts if k in shard or shard.endswith(k[-2:])), None)
        if key is None:
            continue
        truth = salts[key] if gold_tiers is None else {c: gold_tiers.get(c, t)
                                                       for c, t in salts[key].items()}
        judged = {str(r.get("corpusId")): r.get("tier") for r in _jl(p)}
        rows = [(c, t, judged.get(c)) for c, t in truth.items()]
        n = sum(1 for _, _, j in rows if j is not None)
        exact = sum(1 for _, t, j in rows if j == t)
        side = sum(1 for _, t, j in rows if j is not None and (j in POS) == (t in POS))
        stricter = sum(1 for _, t, j in rows if t in POS and j is not None and j not in POS)
        looser = sum(1 for _, t, j in rows if t not in POS and j in POS)
        report[shard] = {"salted": len(rows), "judged": n, "exact": exact, "same_side": side,
                         "stricter_than_gold": stricter, "looser_than_gold": looser,
                         "FLAG": n > 0 and side / n < 0.6}
    return report


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "score":
        gold = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else None
        print(json.dumps(score_salt(sys.argv[2], sys.argv[3], gold), indent=1))
