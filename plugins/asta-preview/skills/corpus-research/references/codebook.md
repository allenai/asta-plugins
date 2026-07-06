# Codebook — grounded aspect vocabulary, DERIVED from this corpus

When a question needs content families (which abilities/methods/phenomena/techniques a corpus
covers), you need a shared tag vocabulary. DERIVE it from THIS corpus — never import a codebook
from another thread (that's a train-test leak and it won't fit).

## Derivation (grounded coding)
1. **Open-code** a sample (titles+abstracts of the relevant set): note the phenomenon/method each
   analyzes, in the papers' own terms.
2. **Cluster** the open codes into ~10–20 families; each family = {name, one-line definition,
   a few exemplar corpusIds}.
3. **Name + freeze** as `codebook@v1`; write `codebook_version` into thread.json.
4. **Apply by exact-match** to every relevant paper as an ordered tag batch
   (`<run>/tag-batches/<NN>-<name>.jsonl`: {corpusId, primary_family, secondary_families, confidence}).
5. **Monitor "Other"** — genuine "other/unclassifiable" (excluding empty-abstract) growing past
   ~10% of the relevant set triggers re-derivation: re-open-code the "Other" pile → codebook@v(N+1)
   → re-tag → rebuild. Bump the version; the substrate stamps it on every record.

## Two failure modes the gates catch (both real)
- **Untagged ≠ Other.** When the relevant set EXPANDS (new acquisition rounds), the new papers
  must be tagged before any distribution analysis, or an inflated "Other" bucket silently distorts
  the family distribution. `substrate.py`'s TAG_GATE fails <90% real-family — do not quote a
  distribution until it passes.
- **Over-conservative tagging.** A batch that dumps classifiable papers into "Other" fails the
  same gate. Re-tag them (they usually fit existing families) rather than inventing families.

## A codebook is also a scope audit
Deriving families exposes clusters that don't belong to the thread's phenomenon (an orthogonal
subfield, a methodology-only cluster). Those become `scope.out_of_scope_families` in thread.json
(when scope.axis == "separate") — the family-based half of the scope test.

## Methods/entities get their own codebook
The same recipe derives a METHODS codebook (normalize free-text method strings into countable
families) or an ENTITY vocabulary — whatever the question aggregates over. Derive per axis.

## Canonicalization maps are DATA — gate them like data
Entity/name canonicalization (model names, method names, dataset names) uses a **2-level scheme**:
raw string → `{canonical_name, family}` (spelling variants → one canonical; versions → one
family). Rules, each learned from a real failure:
- **Frozen artifact, never inline.** The map is a versioned FILE (`canon-map.json`) applied
  deterministically [T]. Inline normalization ships its errors silently; a file is a 30-second
  audit.
- **Attested names only.** `canonical_name` must appear (modulo punctuation/case) somewhere in
  THIS corpus — a title or an extraction. NEVER invent a name; when none is attested, keep the
  raw string as the canonical and assign only `family`. Real failure: parameter sizes became
  phantom versions ("DeepSeek-Coder 33B" → "DeepSeek 33", "1.1B Llama-arch model" → "Llama 1.1").
- **Machine self-check → review queue.** Scan the map for unattested canonical names (normalized
  substring check against the corpus vocabulary); fix or revert each hit; surface UNCERTAIN
  mappings to the user at a beat — a review queue, not silent auto-accept.
- **General rule: pair every "produce X" with "gate X".** Any derived mapping/table ships only
  after an acceptance check on the artifact itself — same discipline as merges and substrates.
