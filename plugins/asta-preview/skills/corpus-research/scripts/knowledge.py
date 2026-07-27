"""knowledge.py — DEPRECATED STUB (primitive-work ruling 3, 2026-07-27; do not grow back).

The anchor primitive FOLDED into vault.py; the rest is retired — the evidence index makes
vault.db the ONE query surface (measured: this API was bypassed with fine outcomes; anchors
were built via ad-hoc joins). Replacements:
  K.anchor(ids)        -> python vault.py anchor <workspace-or-run> <ids-file> [--label L]
                          (library: from vault import anchor, anchor_layers)
  lookup / view joins  -> vault view/union.jsonl + vault.db `rows` table (the derived join)
  grep over fulltext   -> vault.db `cache_fts` (FTS5) · provenance: python vault.py where
                          <workspace> <text-fragment> (evidence index, ladder-rung receipts)

Retained for compatibility ONLY (coverage_signals.report reads the run layers through here):
`load(run)` -> Knowledge(obs, edges, tiers) over the standard run-dir files, and
`Knowledge.anchor` delegating to vault.anchor. This file stays one batch as a pointer.
"""
from __future__ import annotations
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RELEVANT_TIERS = ("in", "relevant")


class Knowledge:
    def __init__(self, obs, edges, tiers):
        self.obs = obs            # corpusId(str) -> observation record
        self.edges = edges        # corpusId(str) -> [reference corpusIds]
        self.tiers = tiers        # corpusId(str) -> tier (FULL labeled universe)

    def tier(self, cid):
        return self.tiers.get(str(cid))

    def is_relevant(self, cid):
        return self.tier(cid) in RELEVANT_TIERS

    def anchor(self, ids, label=""):
        """DEPRECATED delegate -> vault.anchor (same semantics, same return shape)."""
        from vault import anchor
        return anchor(ids, self.tiers, self.obs, self.edges, label=label)


def load(run):
    """Run-dir membership layers (retained for coverage_signals.report). For thread-level
    queries use the vault: vault.py anchor / where, or sqlite over vault.db."""
    obs, tiers, edges = {}, {}, {}
    p = os.path.join(run, "observations.jsonl")
    if os.path.exists(p):
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                obs[str(r["corpusId"])] = r
    p = os.path.join(run, "standardized-relevance.jsonl")
    if os.path.exists(p):
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                tiers[str(r["corpusId"])] = r.get("tier")
    p = os.path.join(run, "edges-cache.json")
    if os.path.exists(p):
        edges = {str(k): [str(x) for x in v] for k, v in json.load(open(p)).items()}
    return Knowledge(obs, edges, tiers)


if __name__ == "__main__":
    raise SystemExit(
        "knowledge.py is DEPRECATED — the anchor primitive folded into vault.py:\n"
        "  python vault.py anchor <workspace-or-run> <ids-file> [--label L]\n"
        "  python vault.py where <workspace> <text-fragment>   (provenance walk)\n"
        "query surface = vault.db (rows · evidence · gate_regression · cache_fts); "
        "see references/vault.md.")
