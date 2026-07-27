# Plan: Expose Theorizer's capabilities in-process in the Hermes harness

**Audience:** Claude Code (implement in phases)
**Status:** Revised after Phase 0. Every claim below is now grounded in a read of the actual
repositories; see `theorizer-hermes-port-phase0-findings.md` for the evidence behind each decision.
Where this document states a constraint, the findings note cites the file and line.

**Revision summary.** Phase 0 changed the shape of this plan in five ways:

1. The tool boundary is the six `@asta.task` capabilities, **not** the internal `Step` enum. No
   step-executor refactor.
2. The deliverable is a **standalone Hermes plugin repo**, not a change to Hermes core.
3. Autodiscovery **cannot** be a Hermes subagent and stays out-of-process; the Theorizer link is an
   in-process callback in `run_mcts`.
4. Three things this plan originally proposed to build **already exist** (handle-only tool returns,
   registration-vs-exposure separation, durable run storage + resume).
5. Two hard gates were discovered that must clear before Phase 1: Theorizer is **unpackaged**, and
   importing it **starts ~30 threads**.

**Scope revision (2026-07-27).** A second pass cut everything the existing code already provides.
Goal 2 asks for intervention *at the fidelity SKILL.md delivers today* — and today's fidelity is
stage-boundary resume by `run_id` plus BYO inputs (`inject_papers` / `inject_schema` /
`inject_extractions` / `inject_theories`, all live in `src/asta/server.py` + `context.py`). That
mechanism ports to in-process unchanged. Consequences:

- **No new state machine** (`core/flow.py` is cut) — the capability sequence + `run_id` + `inject_*`
  *is* the re-enterable flow; the plugin drives it the same way SKILL.md does today (§3.3).
- **No per-step checkpointing, no awaiting-input state** (old Phase 4 is cut) — both exceed today's
  fidelity; suspension in a client-driven flow is simply the absence of the next call (§3.4).
- **No ArtifactStore facade in Theorizer** (`core/artifacts.py` is cut) — handles are `run_id`(+kind),
  reads go through existing `Persistence`, edits go through existing `inject_*` params on the next
  capability call. What little glue is needed lives in the plugin, not in Theorizer (§3.2).
- **Phase 6 shrinks to a config fix** (PaperFinder URL + trace ids), delivered by
  `theorizer-bug-fixes-plan.md`; the search-substrate redirect is deferred (§3.7).
- **Phase 8 folds into Phase 3** — exposure subsets are registration-time `check_fn`/toolset config,
  and credits arrive via the `TheorizerContext` Protocol the plugin implements anyway.

Net: Theorizer changes reduce to (a) packaging + dependency reconciliation, (b) lifting the six
bodies behind a Protocol with a lazy engine singleton, (c) the point fixes in
`theorizer-bug-fixes-plan.md`. Everything else is new plugin-side code or autodiscovery's one
callback parameter.

## Repositories in scope

- **Theorizer** — `../asta-theorizer-internal` (Python; deployed artifact is A2A-only —
  `uvicorn asta.server:app`. The Flask/pywebio web interface is legacy and not in the entrypoint.
  PaperFinder is reached over HTTP at a hardcoded prod URL, *not* a local instance.)
- **Autodiscovery** — `../asta-autodiscovery` (Python ≥3.13; batch MCTS program `run_mcts`, AG2
  agents, sandboxed code execution. No tool bus, no A2A.)
- **asta-plugins** — this repo (Claude Code plugins + `asta` CLI; reaches Theorizer and autodiscovery
  over A2A today)
- **Hermes** — `../hermes-agent` (Nous Research, MIT). Target harness. **We do not modify it.**

---

## 1. Why we're doing this

Theorizer began as an end-to-end pipeline. User feedback showed people need to intervene at
intermediate points (curate the corpus, edit the extracted schema, refine the goal). We addressed that
by exposing fine-grained steps as **A2A capabilities**. That works for humans, and
`plugins/asta-tools/skills/generate-theories/SKILL.md` drives it well.

But every stage boundary in that flow **is an A2A round-trip**: SKILL.md → `asta generate-theories
<subcommand>` → `make_a2a_group` → HTTP/JSON-RPC via asta-gateway → `@asta.task` handler. The seams
exist only as remote calls. For a non-human caller such as autodiscovery, that means paying
serialization + a transport hop + protocol coupling to invoke a function that could sit in the same
address space — and it leaks "there is a remote agent here" into autodiscovery's control loop.

**Root cause:** A2A is doing duty as an *internal* composition bus. A2A is a *perimeter* protocol
(discovery + delegation across process/framework/org boundaries). The fix is to keep A2A at the
harness boundary and compose capabilities *inside* the harness as ordinary Python calls. It's the
MCP-vs-A2A split applied recursively: inside the harness, capabilities are tools; the harness *as a
whole* speaks A2A outward.

**Two honest framings, corrected by Phase 0:**

- *This is prospective, not remedial.* Autodiscovery contains no A2A client today (`grep -rn "a2a"
  packages/` → zero hits; A2A appears only in its web API layer). We are choosing how to add a
  Theorizer↔autodiscovery link that does not yet exist, not removing existing coupling.
- *The existing SKILL.md path is the baseline being replaced, not an alternative.* Its choreography
  (automatic-vs-piecemeal, continue/stop/edit, resume by `task_id`) is a **requirement to preserve**;
  its A2A-per-stage implementation is what goes away.

**The A2A work is not wasted.** Exposing the granular capabilities located the seams between
Theorizer's steps, and the code says so — `Theorizer1.py:208-265` carries a block commented
`# --- Stable seams for the A2A layer ---`. This port re-homes those seams onto a second (in-process)
adapter; it does not re-derive them.

---

## 2. Goals and non-goals

### Goals
1. Theorizer's six capabilities become **in-process Python calls** in Hermes, reachable by the agent
   loop, by a human-facing flow, and by autodiscovery — with **no A2A client on any intra-harness
   path**.
2. Preserve fine-grained human intervention (corpus / schema / goal) and the end-to-end flow, at
   least at the fidelity `generate-theories/SKILL.md` delivers today.
3. Preserve the existing A2A perimeter for external human and cross-org callers, with no behavior
   change.
4. Theorizer and autodiscovery are reachable from one harness instance and share the asta-tools
   literature capabilities where that is genuinely possible (see §3.7).

### Non-goals
- **Do not modify Hermes core.** No new entries in `toolsets.py`, no edits under `tools/`. Hermes's
  Footprint Ladder ranks a new core tool last of six, and its contribution rubric closes in-tree
  third-party integrations outright.
- **Do not refactor Theorizer's step executors — within this plan.** The boundary is `@asta.task`;
  below it the code stays as-is (§3.1). Per-step Hermes driving is a confirmed follow-on
  requirement, handled by `theorizer-hermes-disentanglement-plan.md` (active), sequenced strictly
  after Phases 1–2 here and never interleaved with them.
- **Do not host autodiscovery in the harness process.** It stays a batch program behind a process
  boundary (§3.6).
- **Do not rewrite autodiscovery's control policy.** It keeps its MCTS loop; it gains one callback.
- Do not move large corpora or per-paper evidence through tool arguments/results.
- No change to Theorizer's scientific method/prompts unless required by the refactor.

---

## 3. Target architecture

### 3.1 The boundary is the six `@asta.task` capabilities

`src/asta/server.py` defines exactly six, and they are the port surface: `generate_theory`,
`build_extraction_schema`, `find_and_extract`, `form_theory`, `evaluate_novelty`,
`resume_extraction`.

They are already thin. Each body is ~20–40 lines of the same four moves: `_new_workflow(...)` or
`_resume(run_id, ...)` → optional `inject_papers`/`inject_schema`/`inject_extractions`/
`inject_theories` → assemble a conditional `steps` list → `_run_via_queue(...)`. Their only
transport-shaped input is `ctx: AstaContext`.

So the refactor is narrow and mechanical: **lift `AstaContext` to a Protocol, move the six bodies into
a `core` package, and implement the Protocol twice.**

```python
# core/theorizer/context.py — no knowledge of A2A or Hermes
class TheorizerContext(Protocol):
    def complete(self, message: str) -> None: ...
    def fail(self, message: str) -> None: ...
    def set_metadata(self, key: str, value) -> None: ...
    def emit_message(self, text: str) -> None: ...          # was A2A-internal; see §3.9
    def start_step(self, label: str, parent=None) -> Step: ...   # Step: .update(str), .finish(bool)
    def append_item(self, text: str, parent=None) -> None: ...
    def publish_artifact(self, artifact, parent=None) -> None: ...
    def open_streaming_artifact(self, **kw) -> StreamingArtifact: ...
    @property
    def credits(self) -> Credits | None: ...    # .check(type, n) / .consume(type, n, metadata=)

# core/theorizer/capabilities.py — the EXISTING @asta.task bodies, unchanged apart from the ctx type
def find_and_extract(theory_query: str, *, ctx: TheorizerContext, ...) -> None: ...

# adapters/a2a.py (in asta-theorizer-internal) — perimeter, unchanged behavior
@asta.task("Find and Extract")
def _a2a_find_and_extract(theory_query: Query, ctx: AstaContext = NullContext(), ...):
    return capabilities.find_and_extract(theory_query, ctx=ctx, ...)   # AstaContext satisfies the Protocol
```

**Do not** factor below this line. Phase 0 found that the step executors are
`*_executor(workflow) -> None` procedures mutating a shared dict, dispatched by a `match` statement
onto per-step thread pools; that two parallel module lineages are both loaded via star imports; and
that there is **zero unit coverage of any step executor** (two test files in the whole repo). A
step-level rewrite would be unprotected and buys nothing the capability boundary doesn't.

Also fix the step list wherever this plan's prose implied one: the six live steps are build-schema
(fused with search-query drafting), find+convert, extract, form-theory (self-reflection is *internal*
to it), save-to-disk (load-bearing — novelty reads stores back), novelty-eval. There is no
corpus-curation step and no separate reflect step. `BUILD_EXTRACTION_SCHEMA` and
`FORM_THEORY_PARAMETRIC` are dead enum members the dispatcher no-ops.

### 3.2 Pass artifacts by reference — mostly already handled

A curated corpus can be thousands of papers; evidence extraction is per-paper. These must not flow
through tool args/results. Two mechanisms cover this, and only one is ours to build:

**Hermes already enforces the guard.** `tools/tool_result_storage.py` implements three layers: per-tool
self-truncation; per-result persistence (over threshold → written to
`{tmp}/hermes-results/{tool_use_id}.txt`, replaced in-context with a ~1,500-char preview + path the
model can `read_file`); and a per-turn aggregate budget (200K chars, largest results spill first).
Defaults: 100K per result, 200K per turn, 1,500-char preview, scaled to the model's context window.
**Do not build a bespoke size guard.** Caveat: plugin `ctx.register_tool()` does not accept
`max_result_size_chars`, so plugin tools get the default — keep handle+summary returns as a
construction discipline and treat the harness layer as a backstop.

**The artifact store already exists; do not build a facade over it.** Theorizer's `Persistence.py`
is the store: a `PersistenceBackend` ABC with `FilePersistence` (JSON under
`data/{workflows,theorystores,paperstores}/`) and `PostgresPersistence` (JSONB tables), keyed by
`generation_id`. The handle scheme falls out of what the capabilities already use:

- **A handle is `run_id` (+ an artifact kind: workflow / theorystore / paperstore).** The
  capabilities already return `run_id` and already persist everything under it.
- **Reads** go through existing `Persistence` getters — the plugin calls them directly when it needs
  to show an artifact.
- **Edits** are not an `update()` method — they are the existing BYO-input path: pass the edited
  schema/papers/extractions/theories into the *next* capability call via `inject_schema` /
  `inject_papers` / `inject_extractions` / `inject_theories`. This is how the A2A flow works today
  and it needs no new API.
- **Summaries** are plugin-side formatting of what the capability emitted via `ctx`, not a new store
  method.

Any glue this needs (e.g. a `read_artifact(run_id, kind)` helper) lives in the **plugin**, not in
Theorizer. No new Protocol, no `core/artifacts.py`.

Rule of thumb enforced in review: **a tool return value is a `run_id` plus a short status, and
nothing that scales with corpus size.**

> Note: Hermes's `SessionDB` (SQLite + FTS5) manages *conversation history*. It does not manage domain
> artifacts, and its kanban attachments are not a fit. The domain store is ours.

### 3.3 End-to-end flow = the existing capability sequence, driven in-process

**Do not build a new state machine.** The re-enterable flow already exists at the capability
boundary: each capability runs its stage(s) and persists under `run_id`; the next call resumes via
`_resume(run_id)` and accepts edited artifacts via `inject_*`. That is exactly the
run-to-a-seam → edit → re-enter shape, and it is what SKILL.md choreographs today over A2A:

- run to a seam (e.g. `build_extraction_schema` returns) → nothing is running; the flow is suspended
  by construction
- a human **or** an agent edits the artifact
- the next capability call carries `run_id` + the edited artifact via `inject_*`

Human intervention and machine composition are already the *same* mechanism; the port changes the
transport of each call (A2A → in-process), not the flow. The plugin's piecemeal choreography is a
port of SKILL.md's — a driver over the six capabilities, not new Theorizer code.

**Preserve the SKILL.md choreography** as the UX contract: automatic-vs-piecemeal mode selection,
a decision-oriented summary plus continue/stop/edit after each stage, and resume by run id. Capture
its current behavior before Phase 3 so the in-process path can be compared against it.

### 3.4 Suspend/resume durability — already done; verify, don't build

Phase 0 corrected this section, and the scope revision finished the job. Durable storage and
whole-run resume **already exist**: `PostgresPersistence` when `DATABASE_URL` is set, and
`TheoryGenerationWorkflowStructure.from_persistence(run_id)` reconstructs a run from its persisted
workflow + theorystore + paperstore. `run_id` resume is already an exercised E2E case.

Two things this plan previously proposed are **cut as exceeding today's fidelity** (goal 2 is
parity with SKILL.md, not improvement):

- **Per-step checkpointing** — writes today are sparse (submit, completion, `SAVE_THEORY_TO_DISK`),
  so a mid-run crash re-runs the current capability. That is today's behavior over A2A too. Accept
  it; do not add checkpoint machinery.
- **An explicit awaiting-input state** — unnecessary in a client-driven flow. Between capability
  calls nothing is running; "suspended" is a fact about the persisted `run_id`, not a state to model.
  Hours-later resume already works via `_resume(run_id)`.

The one rule to keep: **never rely on in-memory state for resume** — Hermes's in-conversation async
path is process-local (§3.5). The plugin must treat `run_id` + `Persistence` as the only resume
source, never Hermes session state. This is a discipline to test (AC#8), not a system to build.

### 3.5 Heavy steps run out-of-band — using the harness primitive that is actually durable

Evidence extraction over thousands of papers must not block the agent loop. Hermes has two shapes
here, and Phase 0 found the obvious one is the wrong one:

- `delegate_task(background=true)` returns an id immediately and re-enters via the async-delegation
  completion queue — but AGENTS.md states it is **"detached from the current turn but still
  process-local,"** and points durable work elsewhere. Do not use it for a Theorizer run.
- **`terminal(background=True, notify_on_complete=True)`** is the durable path and the one to use.
- **Cron is not an option for long runs**: cron agent sessions carry a **3-minute hard interrupt**,
  and Theorizer runs 15–25 minutes (novelty adds 30–60).

Convenient consequence: Theorizer's runs are already enqueue-and-poll shaped (`run_id` +
`Persistence`). **The out-of-band phase is therefore "run the packaged core in a background
`terminal` process and poll `run_id` through `Persistence`," not "build a JobRunner."** (Do not
shell out to the existing `asta generate-theories` CLI here — it goes through A2A, which would
reintroduce the hop on an intra-harness path.) Where a tool must expose the pattern directly, keep
it thin:

```python
def _extract(corpus_handle: str) -> str:      # returns job_handle
    return jobs.enqueue(extract_evidence, corpus_handle)

def _status(job_handle: str) -> dict:          # {state, progress, result_handle?}
    return jobs.status(job_handle)
```

### 3.6 Composition: one plugin, two process boundaries

Phase 0 invalidated the "both peers register into one shared tool pool" design, on three independent
findings. The corrected shape:

**Theorizer → in-process tools, via a plugin.** Hermes plugins are discovered from
`~/.hermes/plugins/`, `./.hermes/plugins/`, and pip entry points; each exposes `register(ctx)` and can
call `ctx.register_tool(...)`, `ctx.register_cli_command(...)`, and lifecycle hooks (`pre/post_tool_call`,
`pre/post_llm_call`, `on_session_start/end`). Gate availability with `check_fn` so the tools carry zero
schema footprint when Theorizer isn't configured.

**Autodiscovery → stays out-of-process.** It is not a subagent and cannot be one:

- Hermes subagents are LLM agent loops; autodiscovery is a batch MCTS program with its own sandboxed
  code execution (`backend` ∈ local/process/modal, Modal sandboxes, GCS paths, per-cell `uv` installs).
- It has **no tool bus** — `grep` across all of `packages/` for `register_for_llm`,
  `register_function`, `register_for_execution`, `tools=[]` returns zero hits. Exposing tools to it is
  not a thing that can be done.
- `delegate_task` gives **the model no `toolsets` argument** (`tools/delegate_tool.py:115-116`);
  children inherit the parent's set, and narrowing is a config/code decision.

**The Theorizer↔autodiscovery link is a callback, not a tool call.** Add a hook parameter to
`run_mcts` invoked at the surprisal branch (`run.py:266-278`, where
`all_surprisals.append((node.level, node.node_idx))`) that calls the Theorizer core function directly
in-process. Small, testable, matches the real control flow, needs no tool bus, and respects the
non-goal of not rewriting autodiscovery's control policy.

**Selective exposure is a session-boundary decision.** Hermes treats per-conversation prompt caching
as inviolable: swapping toolsets mid-conversation invalidates the cached prefix and multiplies cost.
So distinct tool subsets for (a) autodiscovery-driven use, (b) the human flow, and (c) the A2A
perimeter must be resolved at session/agent start — via toolset membership and `check_fn` — never
switched at runtime.

### 3.7 Corpus curation → share the *search* substrate only

Theorizer reaches PaperFinder over HTTP at a hardcoded prod URL
(`https://prod-web.ai2i-agents.pandajungle.org/api/2/rounds`), with `caller_actor_id: "test"` and
`cost_trace_id: "test"` hardcoded in the body — so its PaperFinder spend is untraced in prod. Fix that
regardless of this port.

Redirecting curation to asta-tools is only partly possible:

- The step does search **and** full-text acquisition + Mistral OCR (its value is literally
  `find-papers-with-paperfinder-and-convert`). `find-literature` / `local-paper-index` /
  `semantic-scholar` cover search; the acquisition half (`PaperStore.submit_paper`, `MistralOCRStore`,
  the `ocr_cache` tables) has no library equivalent — `pdf-download` / `pdf-extraction` are SKILL.md
  skills, not callable libraries. Extraction and novelty both need OCR'd markdown, so dropping that
  half is a behavior change.
- This repo's `find-literature` itself reaches PaperFinder over A2A
  (`src/asta/literature/client.py`), so "one shared substrate" is the same remote dependency behind a
  different client.

**Scope (revised): fix the config, defer the redirect.** Since `find-literature` reaches the same
remote PaperFinder over A2A, redirecting Theorizer's search half swaps one client for another
without removing the remote dependency — it touches the one executor rated TANGLED for no
architectural gain toward goals 1–3. The URL/trace-id configurability is fix #5 in
`theorizer-bug-fixes-plan.md` (small, worth it regardless, lands before this plan). Defer the
search-substrate sharing until there is an in-process literature capability worth pointing at.

### 3.8 In-process hosting constraints — two gates before Phase 1

Making the capabilities in-process is the whole premise, and it imposes two requirements Phase 0
surfaced. Both are blocking.

**(a) Theorizer must become an installable, namespaced package.** It has no `pyproject.toml`,
`setup.py`, or `setup.cfg`; the container just sets `PYTHONPATH=/app/src`. Its modules are flat and
generically named — `Persistence`, `Struct`, `Throttle`, `Theorizer`, `PaperStore`, … — so importing
them into a shared interpreter would drop 24 top-level names into site-packages with real collision
risk. Package it as a distribution under one namespace (e.g. `asta_theorizer.*`). Note the pervasive
`from X import *` usage means this is a mechanical but non-trivial pass.

**(b) The dependency set must reconcile with Hermes's interpreter.** Hermes installs Python 3.11.
Theorizer's container is `python:3.12-slim` and it pins `litellm==1.60.5`, `numpy==2.2.6`,
`psycopg2-binary`, and a **vendored `mistralai` wheel because the package is quarantined on PyPI**.
Either this reconciles against 3.11 or the core does not load in-process and the port cannot deliver
its premise. **Resolve before Phase 1** — this is the one finding that can invalidate the shape.
(Autodiscovery is unaffected: it requires ≥3.13 but stays out-of-process behind CLI/`terminal`.)

**(c) The core must be import-side-effect-free.** Today `src/asta/server.py:44-45` runs
`loadAPIKeys()` and `theorizer = Theorizer()` at module scope, and that constructor
(`Theorizer1.py:1765-1811`) creates `data/`, a global `PaperStore` (whose `__init__` starts a thread),
its own worker thread, and five `StepProcessor`s each holding a `ThreadPoolExecutor(max_workers=5)` —
one of which constructs `PaperFinderRequests()` (another thread). `Theorizer1.py:47` does a
module-level `os.makedirs`. Importing the entry module starts ~30 threads.

This collides with Hermes running `discover_plugins()` as a side effect of importing
`model_tools.py` — plugins load on ordinary `hermes` invocations, not only when a Theorizer tool is
called. **Therefore:** `register(ctx)` registers only thin handlers; the core is lazy-imported inside
the handler on first call; the engine lives behind a lazily-initialized singleton with shutdown wired
to `on_session_end`.

### 3.9 Component sketch

```
                        ┌──────────────── A2A perimeter (unchanged) ──────────────┐
 external humans / orgs │  Agent Card + JSON-RPC/SSE  →  adapters/a2a.py          │
                        └──────────────────────────────┬──────────────────────────┘
                                                        │  (same six core functions)
 ┌───────────── Hermes process (unmodified core) ───────┴──────────────────────────┐
 │  ~/.hermes/plugins/asta/  →  register(ctx)                                      │
 │    ├─ ctx.register_tool × 6  (thin handlers, check_fn-gated, lazy core import)  │
 │    ├─ ctx.register_cli_command  (piecemeal flow, artifact edit/update)          │
 │    └─ on_session_end  →  engine shutdown                                        │
 │            │                                                                    │
 │            ▼  in-process Python call                                            │
 │  asta_theorizer.core.capabilities  +  TheorizerContext (Hermes impl)            │
 │  existing Persistence (File | Postgres), keyed by run_id — reads + resume       │
 │  edits via existing inject_* params on the next capability call                 │
 └─────────┬───────────────────────────────────────────────────────────────────────┘
           │ terminal(background=True, notify_on_complete=True)   ← durable, out-of-band
           ▼
 autodiscovery (separate process/env, ≥3.13)  ──run_mcts surprisal callback──▶ Theorizer core
```

---

## 4. Phase 0 — complete

Findings: `theorizer-hermes-port-phase0-findings.md`. All seven questions answered; five premises
corrected; two blocking gates identified (§3.8). Read it before starting Phase 1.

---

## 5. Implementation phases

Each phase lands independently with tests green.

- **Phase 1 — Package + core extraction.** Resolve the §3.8 gates first: package Theorizer as
  `asta_theorizer.*` and reconcile deps against Python 3.11. Keep the packaging pass **purely
  mechanical**: move files under the namespace + rewrite imports; no renames, no module splits, no
  `engine/` reorganization. Then lift `AstaContext` to the `TheorizerContext` Protocol and move the
  six `@asta.task` bodies into a `core/capabilities.py` in the same repo, with the engine behind a
  lazily-initialized singleton so importing `core/` has no side effects (§3.8c is satisfied by
  lazy-importing the engine, not by scrubbing the whole module tree). Add unit tests at the
  capability level — there are none today (the D0 characterization suite from the disentanglement
  plan is this floor; land it first). No harness/A2A imports in `core/`. The PaperFinder URL +
  trace-id config fix lands separately via `theorizer-bug-fixes-plan.md` (§3.7).
- **Phase 2 — A2A adapter re-homing.** Rewrite the six `@asta.task` handlers as thin wrappers over the
  core functions (`AstaContext` already satisfies the Protocol). Prove parity against the §6 baseline.
  Perimeter preserved.
- **Phase 3 — Hermes plugin.** Standalone plugin repo installed to `~/.hermes/plugins/asta/`:
  `plugin.yaml` + `register(ctx)`, six `ctx.register_tool` handlers with `check_fn` gating, a Hermes
  `TheorizerContext` implementation (including a Credits impl — the Protocol already carries it),
  handle-only (`run_id`) returns, and reads via existing `Persistence`. Port the `generate-theories`
  piecemeal choreography to in-process calls (driving `run_id` + `inject_*`, §3.3) and retire its A2A
  stage calls. Exposure subsets for each caller class are registration-time config (`check_fn` /
  toolset membership) — absorbed from the old Phase 8; nothing mutates mid-conversation.
- **Phase 4 — Out-of-band heavy steps.** Drive long runs via
  `terminal(background=True, notify_on_complete=True)` — the background process invokes the packaged
  core directly (`python -m asta_theorizer …`), not the A2A CLI, so the no-internal-A2A invariant
  holds. Poll by `run_id` through `Persistence`. The loop never blocks. Do not use background
  delegation or cron.
- **Phase 5 — Autodiscovery link.** Add the `run_mcts` surprisal callback; demonstrate its loop
  invoking a Theorizer capability in-process on a surprising finding, with **no A2A client imported
  anywhere in autodiscovery**.

**Cut from the previous revision** (see scope-revision note): the durable suspend/resume phase
(per-step checkpointing + awaiting-input state — exceeds SKILL.md fidelity, §3.4), the ArtifactStore
facade (§3.2), the asta-tools search redirect (§3.7), and standalone Phase 8 (folded into Phase 3).

---

## 6. Acceptance criteria (write these as tests)

1. **Dual reachability / parity.** The same core function invoked via the A2A adapter and via the
   Hermes plugin handler produces equivalent results on a fixed small fixture.
2. **A2A behavior baseline.** Reuse Theorizer's existing `tests/harness/e2e_matrix.py` +
   `run_e2e_matrix.sh` — it already exercises every skill × every BYO input combination in cost tiers,
   plus `run_id` resume, `file://` paper stores, `resume-extraction`, the full pipeline, and fail-fast
   validation. Capture it before Phase 1; Phase 2 must reproduce it. Do not write new capture tests.
3. **No internal A2A.** Static check: nothing under autodiscovery or the intra-harness paths imports
   an A2A client. CI-enforced (grep/import-linter). Note this passes for autodiscovery today — the test
   is a regression guard, not a fix.
4. **Handle-only returns.** Every Theorizer tool return is a `run_id` + short status. Our own test,
   since plugin-registered tools cannot set `max_result_size_chars` and inherit only the harness
   default.
5. **Import hygiene.** Importing the plugin module starts **no threads** and creates **no
   directories**; the engine initializes lazily on first tool call and shuts down on `on_session_end`.
   Required because Hermes discovers plugins on every CLI invocation.
6. **No Hermes core diff.** CI asserts the port touches no file under `../hermes-agent`.
7. **Intervention.** Run `build_extraction_schema` via the plugin, edit the returned schema, pass it
   to `find_and_extract` via the existing `inject_schema` path with the same `run_id`; the final
   theory reflects the edit. (Exercises today's BYO mechanism in-process — no new machinery.)
8. **Durability.** After a capability completes, kill the process, start a new one, resume via
   `_resume(run_id)` from `Persistence` alone, complete successfully. Guards the "no in-memory resume
   state" rule (§3.4); the mechanism itself already exists.
9. **Non-blocking heavy step.** While extraction runs out-of-band, the loop services other tool calls;
   the result is retrieved by `run_id` on completion.
10. **Peer call.** Autodiscovery's `run_mcts` callback invokes a Theorizer capability in-process and
    consumes the result within its own control policy, end to end.
11. **Exposure subsets.** Distinct toolsets resolve correctly at session start for each caller class
    via registration-time `check_fn`/toolset config, with no mid-conversation toolset mutation
    (prompt-cache safety).
12. **Cost controls.** Credits gating survives the port: an up-front estimate check blocks an
    over-budget run, and a successful run charges exactly once.

---

## 7. Risks / things to watch

- **The §3.8 gates can invalidate the approach.** Unpackaged flat modules and a 3.11-vs-3.12
  dependency set including a PyPI-quarantined wheel are the highest-severity findings. If they don't
  reconcile, "in-process" is unreachable and the plan needs a different shape (e.g. keep Theorizer
  behind HTTP and accept the hop). Resolve first, not opportunistically.
- **Credits and streaming are load-bearing and have no Hermes equivalent.** `credits.py` does an
  up-front `check()` on an estimated paper count and a post-success `consume()` keyed by task id —
  that *is* the cost control this plan asks for, and it is bound to the A2A context. Separately,
  `AstaWorkflow` publishes per-theory / per-extraction / per-paper artifacts plus a streaming
  RFC-7396 Theory Store. Hermes has no artifact concept, so both must be deliberately re-homed
  (files + tool output) or goals 2 and the cost story regress silently.
- **Shared failure/cost domain in one process.** Theorizer at scale is expensive; keep hard limits and
  let heavy work run out-of-band (§3.5).
- **Import-time side effects in a long-lived process.** ~30 threads and directory creation on import
  is a real hazard inside an agent process that loads plugins on every CLI call. AC#5 guards it.
- **Legacy entanglement in Theorizer.** `Theorizer1.py` star-imports 8 modules, two of which pull in
  the older `Theorizer.py` lineage. `core/` can be transport-free; it cannot easily be legacy-free.
  Don't let Phase 1 scope-creep into untangling it.
- **Thin test floor.** Two test files and no step-executor coverage. The E2E matrix is expensive and
  network-dependent. Add capability-level unit tests in Phase 1 before touching anything.
- **Hermes API churn.** The harness moves fast. Isolate all harness-specific calls in the plugin's
  handler + context modules so upstream changes have a small blast radius — and since we ship a
  standalone plugin repo, pin the Hermes versions it's tested against.

---

## 8. Suggested layout

**In `asta-theorizer-internal`** (packaged as `asta_theorizer`):

```
src/asta_theorizer/core/context.py       TheorizerContext Protocol           # no transport imports
src/asta_theorizer/core/capabilities.py  the six @asta.task bodies + lazy engine singleton
src/asta_theorizer/adapters/a2a.py       existing perimeter, now wrapping core
src/asta_theorizer/*.py                  Theorizer1 + legacy lineage, moved verbatim under the
                                         namespace (mechanical import rewrite only — no engine/
                                         subpackage, no renames)
pyproject.toml                           NEW — installable distribution
```

(`core/flow.py` and `core/artifacts.py` from the previous revision are cut — see §3.2/§3.3.)

**Standalone Hermes plugin repo** (installed to `~/.hermes/plugins/asta/`):

```
plugin.yaml                  manifest
__init__.py                  register(ctx): thin tool handlers, CLI commands, on_session_end
hermes_context.py            TheorizerContext implementation for Hermes
handlers/theorizer.py        six handlers; lazy-import the core inside each
tests/                       parity, import-hygiene, handle-only returns, intervention, durability
```

**In `asta-autodiscovery`:** one callback parameter on `run_mcts`, invoked at the surprisal branch.
