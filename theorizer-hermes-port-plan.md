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
- **Do not refactor Theorizer's step executors.** The boundary is `@asta.task`; below it the code
  stays as-is (§3.1).
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

**The artifact store is ours, but it is a facade, not a new system.** Theorizer's `Persistence.py`
already is an ArtifactStore in embryo: a `PersistenceBackend` ABC with `FilePersistence` (JSON under
`data/{workflows,theorystores,paperstores}/`) and `PostgresPersistence` (JSONB tables), keyed by
`generation_id`. What it lacks is per-artifact handles, summaries, `list`, `update`, and session
scoping.

```python
class ArtifactStore(Protocol):          # implemented OVER Persistence.store(), not beside it
    def put(self, kind: str, payload: bytes | dict, *, summary: str) -> Handle: ...
    def get(self, handle: Handle) -> bytes | dict: ...
    def summary(self, handle: Handle) -> str: ...    # cheap; safe to surface to the loop
    def update(self, handle: Handle, payload, *, summary: str) -> Handle: ...   # human edits
    def list(self, session_id: str, kind: str | None = None) -> list[Handle]: ...
```

Rule of thumb enforced in review: **a tool return value is a handle string plus a short status, and
nothing that scales with corpus size.**

> Note: Hermes's `SessionDB` (SQLite + FTS5) manages *conversation history*. It does not manage domain
> artifacts, and its kanban attachments are not a fit. The domain store is ours.

### 3.3 End-to-end flow = checkpointed, re-enterable state machine

Replace the straight pipeline with a state machine whose transitions checkpoint, so re-entry at any
seam is uniform:

- run to a checkpoint (e.g. schema generated) → suspend
- a human **or** an agent edits that artifact via a tool (`update`)
- re-enter at the next transition

Human intervention and machine composition become the *same* mechanism; the only difference is who
edits the artifact between checkpoints. This is what makes the piecemeal flow work without A2A.

```python
# core/theorizer/flow.py
STATES = ["goal", "schema", "papers", "evidence", "theory", "novelty", "done"]

def step(session_id: str, store: ArtifactStore) -> Checkpoint:
    """Advance exactly one transition, persist a Checkpoint, return it. Idempotent per state."""
```

**Preserve the SKILL.md choreography** as the UX contract: automatic-vs-piecemeal mode selection,
a decision-oriented summary plus continue/stop/edit after each stage, and resume by run id. Capture
its current behavior before Phase 3 so the in-process path can be compared against it.

### 3.4 Own suspend/resume durability — but less than we thought

Phase 0 corrected this section. Durable storage and whole-run resume **already exist**:
`PostgresPersistence` when `DATABASE_URL` is set, and
`TheoryGenerationWorkflowStructure.from_persistence(run_id)` reconstructs a run from its persisted
workflow + theorystore + paperstore. `run_id` resume is already an exercised E2E case.

What is genuinely missing, and what Phase 4 must add:

- **Per-step checkpointing.** Writes today are sparse — `save_workflow_to_file()` on submit and on
  completion, plus the `SAVE_THEORY_TO_DISK` step. A mid-run crash loses everything since the last
  write.
- **An explicit awaiting-input state**, so a flow can suspend at a human seam and be resumed hours
  later.

The checkpoint record must be durable and resume must be reconstructable purely from persisted
checkpoint + artifacts. **Never rely on in-memory state for resume** — Phase 0 confirmed Hermes's
in-conversation async path is process-local (§3.5), so this instinct was right. Persist
`{session_id, state, artifact_handles, status, updated_at}` through `Persistence`, not through Hermes
session state.

### 3.5 Heavy steps run out-of-band — using the harness primitive that is actually durable

Evidence extraction over thousands of papers must not block the agent loop. Hermes has two shapes
here, and Phase 0 found the obvious one is the wrong one:

- `delegate_task(background=true)` returns an id immediately and re-enters via the async-delegation
  completion queue — but AGENTS.md states it is **"detached from the current turn but still
  process-local,"** and points durable work elsewhere. Do not use it for a Theorizer run.
- **`terminal(background=True, notify_on_complete=True)`** is the durable path and the one to use.
- **Cron is not an option for long runs**: cron agent sessions carry a **3-minute hard interrupt**,
  and Theorizer runs 15–25 minutes (novelty adds 30–60).

Convenient consequence: Theorizer is *already* a long-running remote service invoked and polled by a
CLI, and `asta generate-theories … --no-wait` already implements enqueue-and-poll. **Phase 5 is
therefore mostly "drive the existing CLI in background mode," not "build a JobRunner."** Where a tool
must expose the pattern directly, keep it thin:

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

**Scope:** share search, keep acquisition + OCR in Theorizer, and verify what `find-literature`
returns before relying on it.

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
 │  ArtifactStore facade  →  asta_theorizer Persistence (File | Postgres)          │
 │  Checkpoint store (per-step + awaiting-input)                                    │
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
  `asta_theorizer.*` and reconcile deps against Python 3.11. Then lift `AstaContext` to the
  `TheorizerContext` Protocol, move the six `@asta.task` bodies into `core/`, and make the module tree
  import-side-effect-free (lazy engine singleton). Add unit tests at the capability level — there are
  none today. No harness/A2A imports in `core/`.
- **Phase 2 — A2A adapter re-homing.** Rewrite the six `@asta.task` handlers as thin wrappers over the
  core functions (`AstaContext` already satisfies the Protocol). Prove parity against the §6 baseline.
  Perimeter preserved.
- **Phase 3 — Hermes plugin.** Standalone plugin repo installed to `~/.hermes/plugins/asta/`:
  `plugin.yaml` + `register(ctx)`, six `ctx.register_tool` handlers with `check_fn` gating, a Hermes
  `TheorizerContext` implementation, session-scoped ArtifactStore facade, handle-only returns. Port the
  `generate-theories` piecemeal choreography to in-process calls and retire its A2A stage calls.
- **Phase 4 — Durable suspend/resume.** Per-step checkpointing and an awaiting-input state over the
  existing `Persistence` backends. Suspend at any seam; resume after a simulated restart; a human edits
  an artifact between checkpoints.
- **Phase 5 — Out-of-band heavy steps.** Drive long runs via
  `terminal(background=True, notify_on_complete=True)`; expose enqueue/poll where a tool needs it. The
  loop never blocks. Do not use background delegation or cron.
- **Phase 6 — Corpus curation on asta-tools (search only).** Redirect the search half to shared
  literature capabilities; leave acquisition + OCR in Theorizer. Fix the hardcoded PaperFinder URL and
  cost-trace identifiers.
- **Phase 7 — Autodiscovery link.** Add the `run_mcts` surprisal callback; demonstrate its loop
  invoking a Theorizer capability in-process on a surprising finding, with **no A2A client imported
  anywhere in autodiscovery**.
- **Phase 8 — Exposure and cost hardening.** Distinct tool subsets resolved at session start for the
  autodiscovery-driven path, the human flow, and the A2A perimeter. Re-home credits gating (§7) and
  enforce per-capability cost limits.

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
4. **Handle-only returns.** Every Theorizer tool return is a handle + short status. Our own test, since
   plugin-registered tools cannot set `max_result_size_chars` and inherit only the harness default.
5. **Import hygiene.** Importing the plugin module starts **no threads** and creates **no
   directories**; the engine initializes lazily on first tool call and shuts down on `on_session_end`.
   Required because Hermes discovers plugins on every CLI invocation.
6. **No Hermes core diff.** CI asserts the port touches no file under `../hermes-agent`.
7. **Intervention.** Run to the schema checkpoint, edit the schema artifact via a tool, resume; the
   final theory reflects the edit.
8. **Durability.** Suspend at a human-input seam, restart the process, resume from persisted
   checkpoint + artifacts, complete successfully.
9. **Non-blocking heavy step.** While extraction runs out-of-band, the loop services other tool calls;
   the result is retrieved by handle on completion.
10. **Peer call.** Autodiscovery's `run_mcts` callback invokes a Theorizer capability in-process and
    consumes the result within its own control policy, end to end.
11. **Exposure subsets.** Distinct toolsets resolve correctly at session start for each caller class,
    with no mid-conversation toolset mutation (prompt-cache safety).
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
src/asta_theorizer/core/capabilities.py  the six @asta.task bodies
src/asta_theorizer/core/flow.py          checkpointed state machine
src/asta_theorizer/core/artifacts.py     ArtifactStore facade over Persistence
src/asta_theorizer/adapters/a2a.py       existing perimeter, now wrapping core
src/asta_theorizer/engine/               Theorizer1 + legacy lineage, lazily constructed
pyproject.toml                           NEW — installable distribution
```

**Standalone Hermes plugin repo** (installed to `~/.hermes/plugins/asta/`):

```
plugin.yaml                  manifest
__init__.py                  register(ctx): thin tool handlers, CLI commands, on_session_end
hermes_context.py            TheorizerContext implementation for Hermes
handlers/theorizer.py        six handlers; lazy-import the core inside each
tests/                       parity, import-hygiene, handle-only returns, intervention, durability
```

**In `asta-autodiscovery`:** one callback parameter on `run_mcts`, invoked at the surprisal branch.
