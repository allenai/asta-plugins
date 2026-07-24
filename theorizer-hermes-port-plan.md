# Plan: Port Theorizer into the Hermes harness as a peer capability

**Audience:** Claude Code (review, then implement in phases)
**Status:** Draft for review. Authored from public documentation, *not* from a read of the
actual source. **Phase 0 is mandatory** — validate every assumption below against the real
repositories before writing implementation code, and flag anything that contradicts this plan.

## Repositories in scope

- Theorizer — https://github.com/allenai/asta-theorizer (Python; today: back-end server +
  web server + programmatic endpoints; depends on a local Asta PaperFinder)
- Autodiscovery — https://github.com/allenai/autodiscovery (Python 3.10+; iterative
  open-ended discovery loop that writes and runs its own experiment code)
- asta-plugins — https://github.com/allenai/asta-plugins (Python; SKILL.md-based plugins;
  `asta` CLI; literature tools: find-literature, local-paper-index, semantic-scholar)
- Hermes harness (Nous Research) — target harness

---

## 1. Why we're doing this

Theorizer began as an end-to-end pipeline. User feedback showed people need to intervene at
intermediate points (curate the corpus, edit the extracted schema, refine the top-level goal).
We addressed that by exposing the fine-grained steps as **A2A capabilities** alongside the
end-to-end flow. That works for humans.

It does **not** work for non-human callers such as autodiscovery. Making autodiscovery embed an
A2A client to reach a Theorizer step means paying serialization + a transport hop + protocol
coupling to call a function that could sit in the same address space — and it leaks "there is a
remote agent here" into autodiscovery's control loop. That is the intrusiveness we want to remove.

**Root cause:** we are using A2A as an *internal* composition bus. A2A is a *perimeter* protocol
(discovery + delegation across process/framework/org boundaries). The fix is to move A2A to the
harness boundary and compose capabilities *inside* the harness over the harness's native tool bus.
It's the MCP-vs-A2A split applied recursively: inside the harness, capabilities are tools; the
harness *as a whole* speaks A2A to the outside world.

**The A2A work is not wasted.** Exposing the granular A2A capabilities already located the seams
between Theorizer's steps. This port re-homes those seams onto a second (in-harness) adapter; it
does not re-derive them.

---

## 2. Goals and non-goals

### Goals
1. Theorizer's steps become first-class **tools** in Hermes, callable by the harness loop, by a
   human-facing flow, and by autodiscovery — with **no A2A client** on any intra-harness path.
2. Theorizer and autodiscovery are **peers** in one harness, sharing a common tool pool and the
   shared asta-tools literature capabilities.
3. Preserve fine-grained human intervention (corpus / schema / goal) and the end-to-end flow.
4. Preserve the existing A2A perimeter for external human and cross-org callers.

### Non-goals
- Do **not** rewrite autodiscovery's control policy. It stays an iterative sub-agent with its own
  loop; it merely gains Theorizer's steps as callable tools.
- Do **not** flatten Theorizer and autodiscovery into a single loop.
- Do **not** move large corpora or per-paper evidence through tool arguments/results.
- No change to Theorizer's scientific method/prompts unless required by the refactor.

---

## 3. Target architecture

### 3.1 Separate each step from its transport
Factor every Theorizer step — at minimum: **curate corpus, generate schema, extract evidence,
generate theory, reflect** (confirm the real list in Phase 0) — into a transport-agnostic core
function over a shared artifact store. Put thin adapters on top.

```python
# core/theorizer/steps.py — no knowledge of A2A or Hermes
def generate_schema(goal: str, corpus: CorpusHandle, *, store: ArtifactStore) -> SchemaHandle:
    ...

# adapters/a2a.py — perimeter (wrap EXISTING A2A capabilities around the core)
@a2a_capability("theorizer/generate_schema")
def _a2a_generate_schema(req):
    return generate_schema(**parse(req))

# adapters/hermes_tools.py — intra-harness peer
@hermes_tool(name="theorizer_generate_schema")
def _tool_generate_schema(goal: str, corpus_handle: str) -> str:  # returns a handle + summary
    return serialize(generate_schema(goal, CorpusHandle(corpus_handle), store=session_store()))
```

The two adapters are the *only* transport-aware code. The core functions are, as far as possible,
the existing Theorizer functions with an explicit typed contract bolted on. Python-to-Python: this
is reuse, not a rewrite.

### 3.2 Pass artifacts by reference, never by value
A curated corpus can be thousands of papers; evidence extraction is per-paper. These cannot flow
through tool args/results without destroying the context window. Every step reads/writes a
**session-scoped ArtifactStore** and exchanges **handles + a one-line summary**, never blobs.

Minimum ArtifactStore contract (reconcile with anything Hermes already provides):

```python
class ArtifactStore(Protocol):
    def put(self, kind: str, payload: bytes | dict, *, summary: str) -> Handle: ...
    def get(self, handle: Handle) -> bytes | dict: ...
    def summary(self, handle: Handle) -> str: ...   # cheap; safe to surface to the loop
    def update(self, handle: Handle, payload, *, summary: str) -> Handle: ...  # for human edits
    def list(self, session_id: str, kind: str | None = None) -> list[Handle]: ...
```

Rule of thumb enforced in review: **a tool return value is a handle string plus a short status,
and nothing that scales with corpus size.** Add a size guard in the Hermes adapter that rejects
oversized returns in tests.

> Note: Hermes's sessions-as-infrastructure and lineage-based context compression manage the
> *conversation history*. They do **not** manage these domain artifacts. The store is ours to build.

### 3.3 End-to-end flow = checkpointed, re-enterable state machine
Replace the straight pipeline with a state machine whose states are the steps and whose transitions
checkpoint to the ArtifactStore. Re-entry at any seam is then uniform:

- run to a checkpoint (e.g. schema generated) → suspend
- a human **or** an agent edits that artifact via a tool (`update`)
- re-enter at the next transition

Human intervention and machine composition become the *same* mechanism; the only difference is who
edits the artifact between checkpoints.

```python
# core/theorizer/flow.py
STATES = ["goal", "corpus", "schema", "evidence", "theory", "reflection", "done"]

def step(session_id: str, store: ArtifactStore) -> Checkpoint:
    """Advance exactly one transition, persist a Checkpoint, return it. Idempotent per state."""
```

### 3.4 Own suspend/resume durability explicitly
This is the part the harness does **not** give us for free. A2A's `input-required` + `tasks/get`
gave clean suspend/resume across a human returning hours later; Hermes's durable child-run
orchestration is reported as still emerging. So the **checkpoint record must be durable** — survive
a harness restart while a flow waits on human curation — and resume must be reconstructable purely
from the persisted checkpoint + artifacts. Do not assume in-memory session state persists.

Ironically, the explicit task-state discipline the A2A design forced on us is exactly what we
preserve internally. Persist: `{session_id, state, artifact_handles, status, updated_at}`.

### 3.5 Heavy steps run as async jobs, even in-process
Evidence extraction over thousands of papers must not block the agent loop as a synchronous tool
call. The tool **enqueues a job and returns a job handle**; the loop polls status. Mirrors A2A's
long-running task lifecycle, but in-process, and prevents one expensive step from monopolizing the
loop or coupling autodiscovery's cadence to Theorizer's.

```python
@hermes_tool(name="theorizer_extract_evidence")
def _extract(corpus_handle: str) -> str:      # returns job_handle
    return jobs.enqueue(extract_evidence, corpus_handle)

@hermes_tool(name="theorizer_job_status")
def _status(job_handle: str) -> dict:          # {state, progress, result_handle?}
    return jobs.status(job_handle)
```

### 3.6 Peer composition + selective exposure
Theorizer is essentially linear → **step-tools + a thin orchestrator**. Autodiscovery is a genuine
iterative loop with its own control policy (surprise scoring, hypothesis selection) → keep it as a
**sub-agent that runs its own loop and consumes the shared tool pool**, including Theorizer's
step-tools. Peer composition = both register into one capability registry; autodiscovery calls e.g.
`theorizer_generate_theory(...)` as a tool when a surprising finding warrants a theory.

Use Hermes's reported separation of **tool registration** from **tool exposure**: register
everything centrally, expose different subsets to (a) autodiscovery, (b) the human-facing flow, and
(c) the A2A perimeter. Confirm this API exists in Phase 0; if not, implement a thin registry
wrapper that provides it.

### 3.7 Corpus curation → shared asta-tools, not a Theorizer-private copy
Theorizer currently needs a local Asta PaperFinder. In the harness that is already a capability
(find-literature / local-paper-index / semantic-scholar). Make "curate the corpus" draw on those
shared tools so Theorizer, autodiscovery, and the user share one literature substrate. This is a
substantive argument for the single-harness approach beyond avoiding the round-trip.

### 3.8 Component sketch
```
                        ┌──────────────── A2A perimeter (existing) ───────────────┐
 external humans / orgs │  Agent Card + JSON-RPC/SSE  →  adapters/a2a.py          │
                        └──────────────────────────────┬──────────────────────────┘
                                                        │  (same core functions)
 ┌───────────────────────── Hermes harness ────────────┴──────────────────────────┐
 │  capability registry (register ≠ expose)                                         │
 │    ├─ theorizer step-tools ── adapters/hermes_tools.py ── core/theorizer/*       │
 │    ├─ asta-tools literature (find/index/search)                                  │
 │    └─ autodiscovery (sub-agent, own loop) ── consumes step-tools + lit tools     │
 │  ArtifactStore (session-scoped, durable)   JobRunner (async heavy steps)         │
 │  Checkpoint store (durable suspend/resume)                                        │
 └──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Phase 0 — Validate assumptions (do this first, report back before coding)

Produce a short findings note answering each. Where reality differs from this plan, propose the
adjustment rather than forcing the plan.

1. **Theorizer step boundaries.** Enumerate the real steps and their current function/endpoint
   boundaries (inspect `TheorizerServer.py`, `TheorizerWebInterface.py`, and the pipeline modules).
   Do the existing A2A capabilities already map 1:1 to clean functions? List the seams.
2. **Theorizer state today.** How is intermediate state (goal, corpus, schema, evidence, theories)
   currently represented and persisted? Files? In-memory? DB? This determines ArtifactStore mapping.
3. **PaperFinder coupling.** How does Theorizer call PaperFinder now, and can corpus curation be
   redirected to asta-tools' literature capabilities without behavior change?
4. **Hermes tool API.** Confirm how tools are registered and invoked; confirm whether
   registration-vs-exposure separation exists; confirm session scoping and any artifact/blob store
   primitive Hermes already offers (avoid reinventing).
5. **Hermes sub-agent model.** Confirm how a sub-agent with its own loop (autodiscovery) is hosted,
   how it's granted a tool subset, and how its lifecycle/cost is bounded.
6. **Durability reality.** Confirm what Hermes persists across restart. Determine exactly what we
   must own for suspend/resume. Confirm whether async/background jobs have any harness primitive or
   must be built.
7. **A2A adapter reuse.** Confirm the existing A2A capability handlers can be refactored to call the
   new core functions with no behavior change (regression baseline in §6).

---

## 5. Implementation phases

Each phase should land independently with tests green.

- **Phase 1 — Core extraction.** Refactor Theorizer steps into transport-agnostic `core/theorizer/`
  functions over an `ArtifactStore` interface. Provide a local filesystem/SQLite ArtifactStore
  implementation. No harness/A2A imports in `core/`.
- **Phase 2 — A2A adapter re-homing.** Rewrite existing A2A capabilities as thin wrappers over the
  core functions. Prove behavior parity against the §6 baseline. (Perimeter preserved.)
- **Phase 3 — Hermes tool adapter.** Register step-tools; enforce handle-only returns + size guard;
  wire session-scoped ArtifactStore. The end-to-end flow becomes the checkpointed state machine.
- **Phase 4 — Durable suspend/resume.** Durable checkpoint store; suspend at any seam; resume from
  persisted state after a simulated restart; human edits an artifact between checkpoints.
- **Phase 5 — Async heavy steps.** JobRunner; evidence extraction (and any other heavy step)
  enqueue/poll; loop never blocks on a long job.
- **Phase 6 — Corpus curation on asta-tools.** Redirect curation to shared literature capabilities.
- **Phase 7 — Peer composition with autodiscovery.** Host autodiscovery as a sub-agent; expose the
  Theorizer step-tools to it; demonstrate its loop invoking `theorizer_generate_theory` on a
  surprising finding, with **no A2A client imported anywhere in autodiscovery**.
- **Phase 8 — Selective exposure hardening.** Distinct exposed tool subsets for autodiscovery, the
  human flow, and the A2A perimeter; per-step cost controls for long runs.

---

## 6. Acceptance criteria (write these as tests)

1. **Dual reachability / parity.** The same core function invoked via the A2A adapter and via the
   Hermes tool adapter produces equivalent results on a fixed small fixture.
2. **A2A behavior baseline.** Capture current A2A capability outputs on a fixture *before* Phase 1;
   Phase 2 must reproduce them.
3. **No internal A2A.** Static check: nothing under autodiscovery or the intra-harness paths imports
   an A2A client. CI-enforced (grep/import-linter rule).
4. **Handle-only returns.** Every Theorizer tool return is a handle + short status; a size guard
   fails the test if a return scales with corpus size.
5. **Intervention.** Run to the schema checkpoint, edit the schema artifact via a tool, resume; the
   final theory reflects the edit.
6. **Durability.** Suspend at a human-input seam, restart the process, resume from persisted
   checkpoint + artifacts, complete successfully.
7. **Non-blocking heavy step.** While evidence extraction runs as a job, the loop can service other
   tool calls; result is retrieved by handle on completion.
8. **Peer call.** Autodiscovery's loop calls a Theorizer step-tool and consumes the result within
   its own control policy, end to end.

---

## 7. Risks / things to watch

- **Durability is ours, not the harness's.** The single biggest correctness risk. Treat the
  checkpoint store as the source of truth; never rely on in-memory session state for resume.
- **Shared failure/cost/provider domain.** One process means autodiscovery and Theorizer share
  faults and spend. Enforce per-step cost controls and allow heavy jobs to run on separate workers
  (the §3.5 pattern accommodates this). Theorizer at scale is expensive — keep hard cost limits.
- **Two loops, one control flow.** Autodiscovery must remain a sub-agent with its own loop; do not
  let its iteration compete with the harness outer loop for control. Verify the sub-agent hosting
  model in Phase 0.
- **Hermes API churn.** The harness is young and moving fast. Isolate all harness-specific calls in
  `adapters/hermes_tools.py` and a thin registry wrapper so upstream changes have a small blast
  radius.
- **Plan authored without source access.** Everything here is a hypothesis until Phase 0 confirms
  it. Prefer adjusting the plan to match the code over bending the code to match the plan.

---

## 8. Suggested layout (reconcile with real repo structure in Phase 0)

```
core/theorizer/        steps.py, flow.py, artifacts.py, jobs.py   # no transport imports
adapters/a2a.py        existing perimeter, now wrapping core
adapters/hermes_tools.py  tool registration + handle serialization + size guard
harness/registry.py    register-vs-expose wrapper (if Hermes lacks it)
harness/subagents/autodiscovery.py  hosting + exposed tool subset
tests/                 parity, durability, intervention, peer-call, no-internal-a2a
```
