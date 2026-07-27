# Plan: Disentangle Theorizer's business logic from its infrastructure

**Audience:** Claude Code (implement in phases)
**Companion to:** `theorizer-hermes-port-plan.md` (the main port plan) and its
`theorizer-hermes-port-phase0-findings.md`. Read those first.
**Code pin:** all `file:line` citations are against `../asta-theorizer-internal` at
commit **`b940c4a`** (`b940c4a306e5fc0b44c08eda4377e419901f22be`, `main`,
"Merge branch 'simplified' into main", 2026-07-17). Line numbers drift on later commits
— re-anchor against this SHA (`git show b940c4a:src/Theorizer1.py`) if they don't match.

**Status:** Grounded. Every claim below is cited to a file:line in
`../asta-theorizer-internal` at the commit above, from a full read of the engine
(`Theorizer1.py`), the science layer (`TheorizerProcessing.py`,
`SchemaExtractionQueue.py`, `EvaluationQualifiedNovelty.py`), the A2A adapter
(`src/asta/*`), and the store/IO modules.

---

## 0. Why this document exists

The main port plan deliberately draws its tool boundary at the **six `@asta.task`
capabilities** and states a hard non-goal: *"Do not refactor Theorizer's step
executors… below it the code stays as-is"* (`theorizer-hermes-port-plan.md` §3.1, §2).
Phase 0 justified that on three grounds — the executors are `*_executor(workflow) ->
None` procedures mutating a shared dict, dispatched onto per-step thread pools; two
parallel module lineages are loaded via star imports; and there is **zero unit
coverage below the capabilities**.

The question this document answers: **is that boundary forced by a genuine tangle of
business logic and infrastructure, or is it a scoping choice?** And if the tangle is
shallower than assumed, **what would it take to expose the steps themselves** so the
Hermes harness can drive Theorizer's *core loop* (the step state machine) directly —
gaining the freedom to reorder, intervene between any two steps, parallelize, resume
per-step, or invoke a single step — rather than calling six coarse black boxes?

**The short answer, up front.** The hypothesis ("business logic is tangled with
infra") is *half right, and the wrong half is the expensive one*. The **science is
already decoupled** — it lives in separate modules behind a single, already-fakeable
LLM seam, and touches neither the workflow god-object, persistence, nor the observer.
What is tangled is the thin layer *between* the science and the harness: the six
executor procedures, the untyped mutable "workflow dict" they use as their inter-step
contract, and the self-advancing thread engine that drives them. That tangle is real
but **mechanical and testable**, not structural. Disentangling it is a bounded
refactor — and because the science is already clean, the payoff (Hermes driving the
core loop) is reachable without rewriting Theorizer's scientific method.

---

## 1. The verdict, with evidence

Theorizer already has **four layers**, not two. The port plan treats them as one
opaque blob below `@asta.task`; they are in fact distinct, and the seam between them
runs in a specific, findable place.

```
  ┌─ @asta.task capabilities ── src/asta/server.py ──────────────────────────┐
  │  6 thin functions: assemble a `steps` list, call _run_via_queue           │  CLEAN
  ├─ CONTROL PLANE ── Theorizer god-object + StepProcessor pools + dispatcher ┤
  │  step SEQUENCE is data; step→worker DISPATCH is a hardcoded match;         │  SEPARABLE
  │  advancement is a self-polling monitor thread                             │  (thin driver already exists)
  ├─ EXECUTOR ENVELOPE ── the six *_executor(workflow) -> None procedures ────┤  ◄── THE TANGLE
  │  read/write an untyped shared dict; self-signal done/error; own blocking  │  MODERATE→TANGLED
  │  poll loops + background threads; inline a few real domain rules          │
  ├─ SCIENCE LAYER ── TheorizerProcessing / SchemaExtractionQueue / Eval*Novelty ┤
  │  plain-args-in, dict-out; single LLM seam; self-reflection internal;      │  MODERATE (leaning CLEAN)
  │  NO workflow-dict / persistence / observer references                     │
  └─ STORES & I/O ── Struct, Persistence, PaperStore, SemanticScholar, …──────┘  MIXED
```

### 1.1 The science layer is already pure-callable

`TheorizerProcessing.py` contains **zero references** to `theory_workflow_structure`,
`save_workflow`, `Persistence`, the observer callbacks, or `theory_store`/`paper_store`
(grep-confirmed). Its entry points take primitives and plain lists and return plain
dicts:

- `convert_theory_request_to_query_and_schema(theory_request:str, model_str:str, …)`
  → `{"output": {…6 schema keys…}, "total_cost": …}` (`TheorizerProcessing.py:17`, return `:202`)
- `build_theory_from_results_single_theory_reflection3(query:str, results:list, …)`
  → `{"theory_response": {…}, "total_cost": …}` (`:227`, return `:694`) — accuracy path
- `build_theory_from_results_single_theory_reflection4_nonsafebasin(…)` (`:1249`) — novelty path
- `consolodate_results_with_subsampling(extracted_results_in:list, max_tokens:int)`
  → `{"data_subsampled": …, "subsampling_rate": float}` (`:2049`) — the one non-LLM function

Self-reflection is **a pure parameter, not an infra loop**: `use_reflection` triggers
one fan-out revise pass over an internal `ThreadPoolExecutor(max_workers=5)`
(`TheorizerProcessing.py:586-597`), one reflection LLM call per theory, no scoring, no
iteration, no external state — pure LLM-in/LLM-out apart from stdout.

Per-paper extraction and novelty scoring live in the same posture: the extraction
prompt + LLM call are `SchemaExtractionQueue.extract_entities_from_paper` /
`mkPrompt` (`SchemaExtractionQueue.py:277-402`); novelty is
`EvaluationQualifiedNovelty.do_qualified_novelty_evaluation_persistence(theorystore_data,
paperstore, …)` which is data-in/data-out at its boundary
(`EvaluationQualifiedNovelty.py:1488`, return `:1569`).

**The single LLM seam already exists, and it is already fakeable.** Every model call
in the entire `src/` tree flows through `getLLMResponseJSON` /
`getLLMResponseJSONWithMetadata` (`ExtractionUtils.py:267`, `:278`) — grep confirms no
other module imports litellm or calls `completion`. The public wrappers short-circuit
to `_fake_llm_response` when `THEORIZER_FAKE_LLM` is set (`ExtractionUtils.py:263-269`).
**This is the enabling fact of the whole plan:** the "no test coverage below
`@asta.task`" obstacle is removable today — the science layer can be exercised
end-to-end with a fake model via one env var, before any refactor.

### 1.2 The executor envelope is the tangle — and it is a *uniform* tangle

All six executors have the same shape (`Theorizer1.py`): read inputs out of
`workflow.theory_workflow_structure` by string key → call one science function → unpack
its result back into the dict by string key → `add_cost_to_key(...)` → type-validate →
signal via `set_current_step_completed()` / `set_error_state(...)` → `add_note(...)`
for progress → (sometimes) write a debug JSON file. The simplest one proves the
pattern: `build_paperfinder_request_executor` (`Theorizer1.py:683-752`) is ~40 lines
around a single call to `convert_theory_request_to_query_and_schema` (`:688`); the
"tangle" is the parse-and-scatter into five dict keys (`:707-711`) and the interleaved
validation/error-state (`:716-724`).

What makes the heavy steps genuinely tangled is that infra concerns are woven *through*
the body rather than sitting at its edges:

- **Blocking poll loops + background-thread ownership inside the executor.**
  `make_paperfinder_request_executor` runs its own submit/poll loop with `time.sleep`
  (`Theorizer1.py:777-786`, `888-913`); `extract_from_papers_executor` spins up a
  25-thread `SchemaExtractionQueue` mid-body (`:971-980`) and runs three poll loops;
  `qualified_novelty_evaluation_executor` registers a background PaperStore
  (`:1702-1705`).
- **Genuine domain rules inlined into those loops** — see §2.
- **Progress emission woven into the science boundary.** `on_paper_retrieved` fires
  from inside the executor loop (`:899-900`), and the novelty observer callback is
  invoked from *inside worker threads* (`EvaluationQualifiedNovelty.py:1559-1562`).

Per-step separability (from the block-level reads):

| Step (executor) | Rating | The single biggest knot |
|---|---|---|
| save-to-disk (`:1580`) | **CLEAN** | none — it *is* infra (becomes `ArtifactStore.put`) |
| build-schema (`:683`) | **MODERATE** | parse-and-scatter into 5 dict keys (`:707-711`) |
| form-theory (`:1333`) | **MODERATE** | `Theory`-construction loop welds object build + `theory_store.add_theory` (`:1504-1536`) |
| find+convert (`:770`) | **TANGLED** | conversion poll loop fuses cutoff-filter + observer + polling (`:888-913`) |
| extract (`:966`) | **TANGLED** | ~190-line follow-on backfill branch mixes ranking + I/O + 2 poll loops (`:1109-1296`) |
| novelty (`:1667`) | **TANGLED** | observer callback fired from inside nested worker threads (`EvaluationQualifiedNovelty.py:1559-1562`) |

### 1.3 The control plane is already separable — a thin driver exists

Step **sequence** is data: the `steps` list, validated by the dispatcher which *fails*
if asked to run a step outside it (`Theorizer1.py:2109-2116`). Step→worker **dispatch**
is a hardcoded `match` (`:2131-2242`). Advancement is a single self-polling monitor
thread (`process_work_monitor`, `:2265`) that calls `increment_step()` then
`dispatch_workflow()` itself. Crucially, a **thin external driver already exists**:
`_run_via_queue` (`server.py:349`) scopes a run to a step *subset* via `set_steps`
(`:371`) and blocks the request thread on a `threading.Event` a worker sets through the
single guarded observer seam (`workflow.py:96`, `:174-189`). "Run just these steps" is
achieved by narrowing data, not by inverting control — but there is **no public
"run exactly one step and return its result" entry point** today.

### 1.4 The stores are mostly fine; two of them hide real rules

| Module | Class | Notes |
|---|---|---|
| `Struct.py` | **PURE-DOMAIN** records | symmetric `to_dict`/`from_dict`; **but** `TheoryStore.__init__` builds a thread-spawning `PaperStore` by default (`Struct.py:23`) and `from PaperStore import *` (`:13`) pulls the whole stack |
| `Persistence.py` | **INFRA (clean)** | one leak: `get_paperstore` returns a live thread-spawning PaperStore, not a dict (`:97`, `:299`) |
| `PaperStore.py` | **MIXED** | store + 10-thread pool + fetch/OCR pipeline; **embedded rules**: license/TDM gate (`:836-851`), full-text = markdown>100 chars (`:669`, `:866`, `:885`), id precedence s2→corpus→title (`:206-216`), ACL-PDF ranking (`:970-972`), arXiv fuzzy-match ≥0.95 (`:1063`) |
| `SemanticScholar.py` | **MIXED** | hardcoded **prod** PaperFinder URL (`:461`) with `caller_actor_id/cost_trace_id = "test"` (`:456-457`); cutoff pushed into the S2 query param (`:43-49`); global mutable cache |
| `SchemaExtractionQueue.py` | **MIXED** | 25-thread queue wrapping a ~95-line inline extraction prompt (`:277-402`) |
| `MistralOCRStore`, `PaperFinderRequests`, `Throttle` | **INFRA** | Throttle (`Throttle.py`) is the one unambiguously pure utility |
| `ExtractionUtils.py` | **MIXED** | the LLM seam (§1.1) + a **duplicated hardcoded model cost table** (`:401-438`, `:643-680`); import-time tiktoken load (`:27`) + mutable global `TOTAL_LLM_COST` (`:18`) |

---

## 2. The real business logic — and where it is hiding

Disentangling means, concretely, giving each of these a pure, typed, testable home.
The science-layer functions are already ~pure (they need typing, not extraction); the
danger is the domain rules currently *buried inside infra*, which are easy to lose
track of during a port.

| Domain rule | Current home | Kind |
|---|---|---|
| query → normalized query + extraction schema | `TheorizerProcessing.convert_theory_request_to_query_and_schema` `:17` | science (pure) |
| per-paper evidence extraction prompt/contract | `SchemaExtractionQueue.mkPrompt` `:278-374` | science (pure, inline prompt) |
| theory formation + self-reflection (accuracy / novelty) | `TheorizerProcessing` `:227` / `:1249` | science (pure) |
| evidence subsampling to token budget | `TheorizerProcessing.consolodate_results_with_subsampling` `:2049` | science (pure, **nondeterministic** — unseeded `random.sample` `:2077`) |
| novelty scoring across 7 fixed dimensions | `EvaluationQualifiedNovelty` (dims `:1001`, `:1253`) | science (threads + live-store reads inside) |
| knowledge-cutoff filtering | executor `Theorizer1.py:804-835` **and** S2 query param `SemanticScholar.py:43-49` | rule (duplicated, inline) |
| paper dedup / selection / id precedence | executor `:863-884` + `PaperStore.py:206-216` | rule (inline) |
| follow-on candidate ranking (rating≥1, title≥10, cap) | executor `:1117-1147` | rule (inline in a poll loop) |
| blank-result & full-text (>100 char) heuristics | executor `:1091-1107` + `PaperStore.py:669` | rule (inline, duplicated) |
| license / TDM "no backdoor" gate | `PaperStore.py:836-851` | rule (inline in fetch pipeline) |
| per-model cost pricing | `ExtractionUtils.py:401-438` & `:643-680` | data (duplicated) |

**The genuinely-hard science coupling is novelty** (`qualified_novelty_evaluation`): its
worker owns *nested* thread pools, reads a live `PaperStore` mid-computation
(`EvaluationQualifiedNovelty.py:921`), mutates the passed-in dict in place (`:1557`),
and fires the progress callback from inside worker threads (`:1559-1562`). Everything
else is either already pure or an inline rule that lifts out cleanly.

---

## 3. The target seam

Replace each step's contract — *"a procedure that mutates a shared untyped dict and
self-signals"* — with *"a pure function that takes typed inputs and returns a typed
result"*, and move every infra concern into a thin per-step **driver/adapter**.

```python
# BEFORE (Theorizer1.py) — infra leaks through the body
def build_paperfinder_request_executor(workflow) -> None:
    workflow.add_note("...")                                  # observer
    result = convert_theory_request_to_query_and_schema(      # science (already pure)
        theory_request=workflow.theory_workflow_structure.get("theory_query", ""), ...)
    workflow.add_cost_to_key("...", result.get("total_cost")) # cost accounting
    workflow.theory_workflow_structure["paper_search_query"] = result["output"][...]  # god-dict write
    ...
    workflow.set_current_step_completed()                     # step-machine signal

# AFTER — pure step, no workflow, no observer, no self-signal
@dataclass
class BuildSchemaOut:
    normalized_query: str
    search_query: str
    schema: ExtractionQuerySchema
    cost: float

def build_schema(theory_query: str, model: str, *, llm: LLM) -> BuildSchemaOut: ...
```

The step returns; it does not advance itself. Cost is a field of the result, not a
mutation. Progress is derived by the *driver* from the sequence of returns, not emitted
from inside the science. The **"core loop" then becomes a sequence of pure step calls
over typed artifacts** — drivable by anything: Theorizer's existing monitor thread
(unchanged, for the A2A perimeter), the A2A adapter, or **Hermes** (as tool calls, a
flow, or an agent loop). That last option is the freedom the request is about: with a
per-step contract, Hermes owns sequencing and can intervene, reorder, parallelize,
resume, or invoke one step in isolation — none of which the six coarse capabilities
allow.

Ports (narrow interfaces the pure steps depend on, so I/O stays injectable and testable):

```python
class LLM(Protocol):        def complete_json(self, prompt, model, **kw) -> tuple[dict|None, str, float]: ...
class PaperSearch(Protocol):  def search(self, query, cutoff) -> list[PaperRef]: ...          # PaperFinder/S2
class PaperAcquisition(Protocol): def acquire(self, refs) -> list[Paper]: ...                  # download + OCR (+TDM gate)
class ArtifactStore(Protocol):  def put(...)->Handle; def get(...); def update(...)  # over Persistence (port-plan §3.2)
```

`LLM` already exists in spirit (`getLLMResponseJSON` + the `THEORIZER_FAKE_LLM` fake);
this makes it an injected dependency instead of a module-global function.

---

## 4. Disentanglement phases

Each phase lands independently, behind the existing capabilities, with tests green. The
A2A perimeter keeps working throughout because the executors are hollowed out
incrementally rather than deleted — an executor that calls a new pure step and then does
its dict-writes is a valid intermediate state.

**Phase D0 — Pin the behavior (do this first; it is cheap and unblocks everything).**
Turn on `THEORIZER_FAKE_LLM` and write characterization tests for the four science
entry points and the six executors at the capability level. There are none today
(`theorizer-hermes-port-plan.md` §7 "thin test floor"); the fake-LLM hook makes them
free to write. This is the safety net the port plan says is missing, and it is a
prerequisite for touching anything below `@asta.task`.

**Phase D1 — Type the science contract.** Give the four `TheorizerProcessing`
functions typed inputs/outputs and *one* error convention. Today they disagree:
`convert_*` puts the payload under `"output"` and raises on error
(`TheorizerProcessing.py:208`); `reflection3` puts it under `"theory_response"` and
returns `None` (`:707-711`); `reflection4` also uses `"theory_response"`, has no
try/except (raises), and silently drops `mission_statement` from its envelope
(`:1624` vs `:698`). Normalize to dataclasses/`TypedDict` + a uniform result envelope.
Fix the two latent bugs surfaced in review while here: `convert_*` ignores its
`max_tokens`/`temperature` on the first call (`:178`), and both reflection functions
reference an unbound `theory_candidate` in their empty-result fallbacks (`:626-644`,
`:1558-1576`). Seed the subsampler's RNG (`:2077`). Replace `from X import *`
(`:10-11`) with explicit imports.

**Phase D2 — Extract the inline domain rules (§2) into a pure `rules.py`.** Cutoff
filter, dedup/id-precedence, follow-on ranking, blank/full-text heuristics, license
gate, and the cost table — each becomes a small pure function with unit tests. This is
where the duplication gets collapsed (cutoff and full-text-threshold each live in two
places) and where the hardcoded prod PaperFinder URL + `caller_actor_id="test"` /
`cost_trace_id="test"` get fixed (`SemanticScholar.py:456-461`) — the port plan already
calls this out as worth fixing regardless (§3.7).

**Phase D3 — Make the LLM seam injectable.** Wrap `getLLMResponseJSON` behind the `LLM`
port; thread cost through return values instead of the module-global `TOTAL_LLM_COST`
(`ExtractionUtils.py:18`); make the prompt-debug file writes (`:314-322`) opt-in. Keep
the `THEORIZER_FAKE_LLM` fake as the default test double. Small, high-leverage,
unblocks constructor-injected fakes in unit tests.

**Phase D4 — Hollow out the CLEAN/MODERATE executors into pure steps.**
save-to-disk → `ArtifactStore.put` (it is already pure infra); build-schema and
form-theory → thin drivers over the now-typed science, with the parse-and-scatter
(`:707-711`) and the `Theory`-construction loop (`:1504-1536`) reduced to
`result → typed artifact → store.put`. Each executor becomes: call pure step, persist
result, emit progress from the return. Import-side-effect cleanup lands here too — stop
constructing threads at import / in `TheoryStore.__init__` (`Struct.py:23`), matching
the port plan's AC#5.

**Phase D5 — Untangle the TANGLED steps behind ports.**
- *find+convert*: split into `select_papers()` (pure: cutoff filter + dedup, from D2)
  and a `PaperAcquisition` port that owns the submit/poll/OCR loop
  (`Theorizer1.py:770-947`). Acquisition + OCR is irreducible I/O — it stays behind the
  port, not in the pure core (consistent with port-plan §3.7).
- *extract*: split the ~190-line backfill branch (`:1109-1296`) into
  `rank_followon_candidates()` + `flatten_extracted_data()` + `summarize_outcome()`
  (pure) and an `ExtractionRunner` port that owns the 25-thread fan-out
  (`SchemaExtractionQueue`).
- *novelty* (hardest): pre-resolve paper texts to plain strings *before* the worker
  (kill the live-`PaperStore` read at `EvaluationQualifiedNovelty.py:921`), lift the
  observer callback out of the worker threads (`:1559-1562`) to the driver, and make
  the per-statement scorer a pure `score_statement_novelty(statement, paper_texts,
  models) -> NoveltyResult`.

**Phase D6 — Expose the core loop to a driver, and let Hermes drive it.** With steps
pure and typed, add a public `run_step(state) -> StepResult` entry (the missing
"one step and return" primitive, §1.3), keeping the internal monitor-thread engine only
for the A2A perimeter. The Hermes plugin (port-plan Phase 3) then drives the sequence
step-by-step. **Per-step checkpointing (port-plan Phase 4) falls out for free**: each
pure step's typed return *is* a checkpoint. Autodiscovery (port-plan Phase 7) can invoke
a single step (e.g. novelty-only) rather than a coarse capability.

---

## 5. Acceptance criteria (write these as tests)

1. **Fake-LLM floor.** The four science functions and six capabilities run under
   `THEORIZER_FAKE_LLM=1` with no network and no live model (D0).
2. **Typed contract, one envelope.** All science entry points share a result type and a
   single error convention; the `mission_statement`-drop and `max_tokens`-ignored and
   unbound-`theory_candidate` bugs are fixed and regression-tested (D1).
3. **Rules are pure and de-duplicated.** Cutoff filter and full-text threshold each have
   exactly one implementation, unit-tested; the PaperFinder URL and trace ids are
   configurable, not hardcoded to prod/`"test"` (D2).
4. **Injectable LLM.** A pure step can be unit-tested with a constructor-injected fake
   LLM; no test writes `prompts/*.txt` or mutates a global (D3).
5. **A step is a pure function.** `build_schema` / `form_theories` / `score_statement_novelty`
   take typed inputs and return typed outputs with `cost` as a field — no `workflow`,
   no observer, no self-signal (D4/D5). Static check: `core/` steps import neither the
   workflow god-object nor the observer.
6. **Parity preserved.** Theorizer's existing `tests/harness/e2e_matrix.py` reproduces
   (the port plan's AC#2 baseline) after each phase — the A2A perimeter is unchanged.
7. **Core loop is externally drivable.** A test harness drives the full sequence via
   `run_step` one step at a time, editing an artifact between two steps, with no
   internal monitor thread running (D6). This is the concrete proof that Hermes can own
   the loop.

---

## 6. Cost, risk, and the honest recommendation

**How clean is the split? Cleaner than the port plan assumes, in the layer that
matters.** The expensive-to-untangle part of most legacy pipelines — the domain science
welded to the framework — is *already* separated here: one LLM seam, a fake-LLM mode,
and science modules with zero god-object/persistence/observer references. What remains
is ergonomic and mechanical: type the contracts, extract ~7 inline rules, inject the
LLM, and hollow out six uniform envelopes. The only genuinely structural knot is
novelty's threads-and-live-store worker, and it is one function.

**Risks specific to this deeper refactor** (beyond the port plan's own §7):

- **It crosses the port plan's stated non-goal.** §3.1 says don't factor below
  `@asta.task`, citing no coverage and two star-import lineages. D0 removes the coverage
  objection (the fake-LLM harness). The lineage objection stands — so **scope
  discipline is mandatory**: make `core/` transport- and infra-free; do **not** try to
  make it legacy-free (the `Theorizer.py` lineage pulled in via star imports). That is a
  separate, unbounded fight.
- **`import *` masks provenance** (`TheorizerProcessing.py:10-11`, `Struct.py:13`,
  `SchemaExtractionQueue.py:16-19`). Explicit imports (D1) are a prerequisite, not
  optional polish — you cannot safely move a function whose dependencies are invisible.
- **Novelty is the schedule risk.** Budget D5's novelty untangle as its own increment;
  it is the one step that is TANGLED in the science, not just the envelope.

**Recommendation — when to do this, and when not to.** If the only goal is
"autodiscovery calls Theorizer in-process," the six capabilities are sufficient and this
work is overkill — do the main port plan and stop. Do **this** plan only if the freedom
it buys is actually wanted: per-step human/agent intervention, reordering, single-step
reuse, and free per-step checkpointing — i.e. Hermes *driving* the core loop rather than
invoking it. The request ("port the core loop into the Hermes harness") is exactly that
case, so the recommended sequence is: **port-plan Phase 1–2 first (the minimum in-process
port), then interleave D0–D3 as a low-risk hardening pass behind the capabilities, then
D4–D6 to expose the steps.** D0–D3 are worth doing even if D4–D6 never happen — they fix
real bugs, add the missing test floor, and untrace-fix the prod PaperFinder spend, all
without changing the tool boundary.

---

## 7. Suggested layout (extends port-plan §8)

```
src/asta_theorizer/core/
  steps.py        the six steps as pure typed functions (build_schema, find+acquire,
                  extract, form_theories, save→ArtifactStore.put, score_novelty)
  rules.py        extracted inline domain rules (cutoff, dedup, ranking, thresholds,
                  license gate, pricing) — pure, unit-tested
  ports.py        LLM / PaperSearch / PaperAcquisition / ArtifactStore Protocols
  loop.py         run_step(state) -> StepResult; the data-driven sequence
  science/        thin re-exports of TheorizerProcessing / EvaluationQualifiedNovelty,
                  now typed and explicit-import
adapters/a2a.py   existing perimeter: the monitor-thread engine drives loop.py unchanged
```

The Hermes plugin (port-plan Phase 3) imports `core/loop.py` and drives it step-by-step;
the A2A adapter keeps the internal engine. Same steps, two drivers — which is the whole
point.
