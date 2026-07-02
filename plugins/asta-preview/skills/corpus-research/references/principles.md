# Design principles (P1–P7) — the acceptance bar behind every step

1. **User touches the sources.** "Connected to sources" is user-side: hand verbatim excerpts +
   pointers into papers, not only synthesis. Provenance is necessary but not sufficient.
2. **Learning is the spine; interrogation is one mode.** Flex between rigorous corpus
   interrogation and other modes on user signals; don't lock into one.
3. **Good primitives over rigid schemas.** A small set of flexible primitives the agent composes,
   documented capabilities — not a heavy contract per artifact. Let rigor emerge where load-bearing.
4. **Surface the goal; steer to well-supported operations.** After a few interrogation turns, make
   the user's higher-level goal explicit; if a requested micro-operation stretches the tooling to
   where it performs poorly, propose a more reliable route to the same goal.
5. **Adopt/extend proven components; reinvent nothing that exists — but build what's new.** Reuse
   internal (retrieval/snowball/centrality) and external (exact statistical estimators) proven
   pieces; the genuinely-new parts (aspect codebook, curation recipe, reason-over-coverage,
   unseen-class layer, standardized relevance, the signal suite) are the real build. Check prior
   art before re-deriving.
6. **Cache everything fetched; fetch-once, reuse-forever.** Metadata, abstracts, references,
   citations, snippets, full text — all to a local cache; re-running with the network off is the
   bar. Refetching is the anti-pattern.
7. **Corpus-first.** Build ONE rich corpus, then work OVER it; querying the OWN store is the
   default, external reach is deliberate expansion that folds back in. Parametric PROPOSES, the
   corpus ADJUDICATES. Corpus-first is trustworthy ONLY with an honest boundary signal — else it's
   a filter bubble.

**Cross-cutting:** Trust = place (papers, not parametric) + process (grounded map, not regex) +
coverage (explored + exploited + reasoned, with an estimate + boundary). T/J split: deterministic
computation is a real tool; judgment is a subagent — never fake precision on either side.
Everything versioned + provenanced so improvement is measurable.
