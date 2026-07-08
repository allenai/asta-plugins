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

## Parametric family anchor — REQUIRED gate after codebook@v1 (§anchor)
A corpus-derived codebook is circular by construction: a whole missing family produces no
"Other" growth, no tag-gate failure, nothing. The anchor is the validated check for that class
(caught 4 real families hidden in a real run's "Other"; correct null on a good codebook;
charter-conditioning is the false-positive control — 15/20 spurious naive → 0 conditioned):
> **Protocol.** Reading ONLY the thread charter (question, deliverables, out_of_scope_families)
> — NOT the codebook or corpus — enumerate 12–25 content families you'd expect this literature
> to span, with one-line definitions; WRITE THEM DOWN before opening the codebook. Then align
> each to the codebook: PRESENT / SUBSUMED / ABSENT. For every ABSENT family, title-scan the
> run's candidates and core: (a) papers in-core → carve out the family or add it as a NAMED
> residual (never silently in Other); (b) papers in candidates but not core → audit the
> curation/scope decision; (c) papers nowhere → thin-literature note or an acquisition probe.
> For SUBSUMED families with substantial in-core mass, consider promotion at codebook@v2.
> Record the table in the run's coverage evidence; the gate FAILS if any ABSENT-case-(a) family
> is left uncarved and unnamed.
The anchor is one-directional (it misses families you didn't think to enumerate) — it
complements grounded open-coding, never replaces it.

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
  phantom versions ("FooCoder 33B" → "Foo 33", "a 1.1B Bar-architecture model" → "Bar 1.1").
- **Machine self-check → review queue.** Scan the map for unattested canonical names (normalized
  substring check against the corpus vocabulary); fix or revert each hit; surface UNCERTAIN
  mappings to the user at a beat — a review queue, not silent auto-accept.
- **General rule: pair every "produce X" with "gate X".** Any derived mapping/table ships only
  after an acceptance check on the artifact itself — same discipline as merges and substrates.
