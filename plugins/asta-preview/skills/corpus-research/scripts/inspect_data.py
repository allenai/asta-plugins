"""inspect_data.py — [T] OPTIONAL convenience verbs for the three highest-repetition ad-hoc shapes
(measured: 490 one-liners across 10 runs / 4 domains; these skeletons replicate cross-domain —
eval/mining/oneliner-census.md in the movement repo).

OFFERED, NEVER REQUIRED (P3 sweet-spot criterion): inline python is always legitimate — these
exist to save the re-typing, not to gate anything. Uptake is measured; unused verbs get demoted.

  python inspect_data.py peek  <file.json|.jsonl>            # shape: keys, first record, row count
  python inspect_data.py tally <file.jsonl> <field> [field2]  # value counts for a field (dotted ok)
  python inspect_data.py check <file.jsonl> --require f1,f2   # per-file integrity: parse, required
                                                          # fields non-null, corpusId unique+str
next: for run-LEVEL invariants use validate.py; for membership/joins use knowledge.py.
"""
from __future__ import annotations
import json
import sys
from collections import Counter


def _rows(p):
    if p.endswith(".jsonl"):
        for line in open(p):
            if line.strip():
                yield json.loads(line)
    else:
        d = json.load(open(p))
        if isinstance(d, list):
            yield from d
        else:
            yield d


def _get(r, dotted):
    cur = r
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def peek(p):
    n, first, keys = 0, None, Counter()
    for r in _rows(p):
        n += 1
        if first is None:
            first = r
        if isinstance(r, dict):
            keys.update(r.keys())
    print(f"{p}: {n} record{'s' if n != 1 else ''}")
    if first is None:
        return
    print("keys (count present):")
    for k, c in keys.most_common():
        print(f"  {k}: {c}")
    print("first record:")
    print(json.dumps(first, indent=1)[:1500])


def tally(p, fields):
    counts = Counter()
    n = 0
    for r in _rows(p):
        n += 1
        key = tuple(str(_get(r, f)) for f in fields)
        counts[key if len(fields) > 1 else key[0]] += 1
    print(f"{p}: {n} records · tally by {' × '.join(fields)}")
    for k, c in counts.most_common():
        print(f"  {c:6d}  {k}")


def check(p, require):
    n, bad_parse, missing, ids = 0, 0, Counter(), Counter()
    for line in (open(p) if p.endswith(".jsonl") else []):
        if not line.strip():
            continue
        n += 1
        try:
            r = json.loads(line)
        except Exception:
            bad_parse += 1
            continue
        for f in require:
            if _get(r, f) in (None, "", []):
                missing[f] += 1
        cid = r.get("corpusId")
        if cid is not None:
            ids[str(cid)] += 1
            if not isinstance(cid, str):
                missing["corpusId:NOT-A-STRING"] += 1
    dupes = {k: v for k, v in ids.items() if v > 1}
    fails = []
    if bad_parse:
        fails.append(f"{bad_parse} unparseable lines")
    for f, c in missing.items():
        fails.append(f"{c} records missing/empty '{f}'")
    if dupes:
        fails.append(f"{len(dupes)} duplicate corpusIds e.g. {list(dupes)[:5]}")
    for f in fails:
        print(f"  ✗ {f}")
    print(f"CHECK {'FAIL' if fails else 'PASS'}: {p} ({n} lines)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("peek", "tally", "check"):
        print(__doc__)
        sys.exit(0)
    if a[0] == "peek":
        peek(a[1])
    elif a[0] == "tally":
        tally(a[1], a[2:])
    else:
        req = []
        if "--require" in a:
            req = a[a.index("--require") + 1].split(",")
        check(a[1], req)
