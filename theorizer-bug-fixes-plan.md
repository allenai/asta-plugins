# Plan: Theorizer point bug/config fixes

**Audience:** Claude Code (implement as one small PR, or one commit per fix)
**Companion to:** `theorizer-hermes-port-plan.md` and `theorizer-hermes-disentanglement-plan.md` —
but **independent of both**: nothing here changes a contract, boundary, or module layout, and this
plan can (and should) land before either.
**Code pin:** `../asta-theorizer-internal` at commit **`b940c4a`**
(`b940c4a306e5fc0b44c08eda4377e419901f22be`, `main`) — the same pin as the disentanglement plan.
Re-anchor line numbers against that SHA if they don't match.

## Why a separate plan

These fixes were originally embedded in the disentanglement plan's D1/D2 phases. They are split out
because they are point fixes to real defects — valuable regardless of any refactor, and small
enough that tying them to a refactor phase only delays them. Ground rules:

- **Additive changes only.** No signature breaks (new params get defaults that preserve current
  behavior); no envelope keys removed.
- **Every fix ships with a regression test** that fails on the pre-fix code, using the existing
  `THEORIZER_FAKE_LLM` hook (`ExtractionUtils.py:263-269`) or request capture — no network, no live
  model.
- **No refactoring "while here."** Envelope normalization, rule extraction, import cleanup, and LLM
  injection belong to the disentanglement plan (D1–D3), not this one.

## The fixes

### 1. Unbound `theory_candidate` in empty-result fallbacks

`TheorizerProcessing.py:626-644` (`…reflection3`) and `:1558-1576` (`…reflection4`): when the model
returns no theories, the fallback branch references `theory_candidate`, which is never bound on
that path — so the empty-result case raises `NameError` instead of returning the fallback envelope.
Fix the fallbacks to construct their envelope without the unbound name.
**Test:** fake LLM returns an empty theory list; assert the fallback envelope is returned, no
exception.

### 2. `convert_theory_request_to_query_and_schema` ignores `max_tokens` / `temperature`

`TheorizerProcessing.py:178`: the first LLM call drops the caller's `max_tokens` and `temperature`
arguments. Pass them through.
**Test:** fake-LLM capture asserts both params reach the LLM seam.

### 3. Unseeded subsampler RNG

`TheorizerProcessing.py:2077` (`consolodate_results_with_subsampling`): unseeded `random.sample`
makes evidence subsampling nondeterministic run-to-run. Add an optional `rng` (or `seed`) parameter
defaulting to current behavior; callers that need determinism pass it.
**Test:** same seed → identical subsample; omitted seed → current behavior.

### 4. `mission_statement` silently dropped from the novelty-path envelope

`TheorizerProcessing.py:1624` vs `:698`: `reflection4`'s result envelope omits `mission_statement`
where `reflection3` includes it. Add the key (additive — nothing removed).
**Test:** envelope parity on the shared keys across the two reflection paths.

### 5. Hardcoded prod PaperFinder URL and `"test"` trace identifiers

`SemanticScholar.py:456-461`: the PaperFinder base URL is hardcoded to prod
(`https://prod-web.ai2i-agents.pandajungle.org/api/2/rounds`) and every request carries
`caller_actor_id: "test"` / `cost_trace_id: "test"` — Theorizer's PaperFinder spend is untraced in
prod. Make all three configurable (env vars, with the current values as defaults so behavior is
unchanged until deployments set them); update the deployment config to set real identifiers.
**Test:** env overrides are honored in the request URL and body; defaults match today's values.

## Acceptance criteria

1. Each fix has a regression test that fails on the pre-fix code and runs with no network.
2. No public signature changes except additive defaulted params; no envelope key removed.
3. Theorizer's existing e2e matrix (`tests/harness/e2e_matrix.py`) still passes — perimeter
   behavior unchanged.
4. PaperFinder URL and trace ids honor env overrides and default to today's values; prod deployment
   config sets real identifiers.
