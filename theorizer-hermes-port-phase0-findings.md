# Phase 0 findings — Theorizer → Hermes port plan

**Sources read:** `../asta-theorizer-internal`, `../asta-autodiscovery`, `../hermes-agent`, and this
repo (`asta-plugins`). Public repos not used.

**Scope note (from review):** the units to expose as harness tools are the six functions decorated
`@asta.task` in `../asta-theorizer-internal/src/asta/server.py` — *not* the internal `Step` enum. Q1
is answered at that granularity. This makes Phase 1 dramatically smaller than the plan assumes, and
it is the single most important correction in this document.

**Verdict:** the diagnosis (A2A used as an internal composition bus) holds, and the claim that the
A2A work already located the seams is literally true — the seams are named as such in the code. All
seven questions are now answerable. But five load-bearing premises are wrong, the port is *smaller*
than planned in one dimension (no step refactor) and *differently shaped* in three others (Hermes's
Footprint Ladder rejects new core tools; autodiscovery cannot be a subagent; Hermes's async job
primitive is explicitly non-durable).

**Headline corrections**

| Plan says | Reality |
|---|---|
| Steps are curate corpus / generate schema / extract evidence / generate theory / reflect, factored into `generate_schema(goal, corpus, store)`-style functions | The tool units are the six `@asta.task` capabilities. They already exist as thin Python functions. No step-level refactor is needed or wanted |
| "depends on a local Asta PaperFinder" | Hardcoded HTTP call to a **prod** PaperFinder URL; the local path is commented out |
| Register step-tools into the harness toolset (§3.3, Phase 3) | Hermes's Footprint Ladder makes a new core tool rung 6 of 6, last resort; in-tree third-party integrations are closed on sight. This must be a **standalone plugin repo** |
| Autodiscovery becomes a Hermes sub-agent consuming the shared tool pool (§3.6, Phase 7) | Hermes subagents are LLM agent loops; autodiscovery is a batch MCTS program with **no tool bus at all**. Also: `delegate_task` exposes no `toolsets` argument to the model |
| Autodiscovery would need to embed an A2A client (the intrusiveness to remove) | Autodiscovery has **no A2A anywhere** in its packages today |

**Things the plan proposes to build that already exist** — handle-only returns + size guard (Hermes
`tool_result_storage.py`), registration-vs-exposure separation (Hermes registry vs `toolsets.py`),
durable run storage + whole-run resume (Theorizer `Persistence.py` + `from_persistence`), and the
A2A regression baseline (Theorizer `tests/harness/e2e_matrix.py`).

---

## Q1 — Theorizer step boundaries

### The answer: the six `@asta.task` capabilities

`src/asta/server.py` defines exactly six, and they are the port surface:

| `@asta.task` | Function | Composes (`Step`s) |
|---|---|---|
| Literature Theory Generation | `generate_theory` | build-schema → find+convert → extract → form-theory → save → novelty (4–6, conditional) |
| Build Extraction Schema | `build_extraction_schema` | build-schema (1) |
| Find and Extract | `find_and_extract` | build-schema → find+convert → extract → save (3–4) |
| Form Theory | `form_theory` | form-theory → save (2) |
| Evaluate Novelty | `evaluate_novelty` | (save →) novelty (1–2) |
| Resume Extraction | `resume_extraction` | extract → save (2) |

**These are already thin functions.** Each body is ~20–40 lines of the same four moves:

1. `_new_workflow(theory_query, ctx, **params)` or `_resume(run_id, ctx, **overrides)`
2. optionally `inject_papers` / `inject_schema` / `inject_extractions` / `inject_theories`
3. assemble a conditional `steps` list
4. `_run_via_queue(ctx, workflow, steps, completion_message)`

So §3.1's premise is right at *this* granularity and wrong at the granularity it wrote the sketch
for. There is no need for a `core/theorizer/steps.py` containing
`generate_schema(goal, corpus, *, store) -> SchemaHandle`. **Replace that sketch.** The real refactor
is narrower and mechanical:

> Each `@asta.task` body already takes `ctx: AstaContext` as its only transport-shaped input. Lift
> `AstaContext` to a **Protocol**, move the six bodies into `core/`, and write two implementations of
> the Protocol — the existing `AstaContext` (A2A) and a new Hermes tool context.

That is the whole of Phase 1 + Phase 3. It is genuinely "reuse, not a rewrite."

**The Protocol surface** — the complete set of `ctx` members used across `server.py`, `workflow.py`,
and `credits.py`, i.e. exactly what a Hermes adapter must implement:

- lifecycle: `complete(message)`, `fail(message)`, `set_metadata(k, v)`
- progress: `start_step(label, parent=None)` → step handle with `.update(text)`, `.finish(is_success)`;
  `append_item(text, parent=)`
- artifacts: `publish_artifact(artifact, parent=)`, `open_streaming_artifact(...)` → handle with
  `.append_part(dict)`, `.finalize(dict)`, `.artifact_id`
- cost: `credits.check(type, n)`, `credits.consume(type, n, metadata=)`, `credits.has_credits_backend()`
- (debt) `_update_task_style` internals — see Q7

Ten-ish methods. Well-bounded, and the honest measure of the port's cost.

### Supporting detail: what the capabilities compose

Worth recording because it corrects the plan's step list and flags dead code, even though no
step-level refactor is needed.

`Step` (`Theorizer1.py:60`) — six live, two dead:

| Step | Status | What it actually does |
|---|---|---|
| `INIT` | live (no-op) | dispatcher marks complete immediately |
| `BUILD_PAPERFINDER_REQUEST` | live | normalizes the theory query, drafts the paper search query, **and generates the extraction schema**. Its processor labels itself `Step.BUILD_EXTRACTION_SCHEMA.value` (`Theorizer1.py:758`) |
| `BUILD_EXTRACTION_SCHEMA` | **dead** | dispatcher no-ops it (`Theorizer1.py:2174`: "isn't actually used, since the query currently gets generated in the PaperFinder request step") |
| `FIND_PAPERS_WITH_PAPERFINDER` | live | search **+ PDF acquisition + Mistral OCR conversion** (value is `find-papers-with-paperfinder-and-convert`) + knowledge-cutoff filtering |
| `EXTRACT_FROM_PAPERS` | live | per-paper fan-out via `SchemaExtractionQueue` |
| `FORM_THEORY_PARAMETRIC` | **dead** | "faux dispatch", marks complete (`Theorizer1.py:2209`) |
| `FORM_THEORY_FROM_LITERATURE` | live | subsamples evidence to `max_data_tokens`, synthesizes theories; **self-reflection is inside this step** (`src/asta/workflow.py:70`) |
| `SAVE_THEORY_TO_DISK` | live | load-bearing, not bookkeeping — novelty reads stores back from persistence, so BYO-theory runs must include it (`server.py:275`) |
| `QUALIFIED_NOVELTY_EVALUATION` | live | per-statement novelty across seven dimensions |

So: no corpus-curation step, no reflect step, schema generation fused into the search step, and the
plan omits both save and novelty. Fix §3.1/§3.3's step list accordingly.

**Below the capabilities, the code is not function-shaped** — each step is a
`*_executor(workflow) -> None` procedure mutating a shared dict, dispatched by a `match` statement
(`Theorizer1.py:2105`) onto per-step `StepProcessor` thread pools, with `_run_via_queue` blocking on a
`threading.Event`. This is *why* the tool boundary belongs at `@asta.task` and not below it. Two
further reasons not to go deeper:

- **Two parallel lineages, both loaded.** `Theorizer1.py:16-27` star-imports 8 modules, two of which
  (`SchemaExtractionQueue`, `EvaluationQualifiedNovelty`) do `from Theorizer import *` — the live
  engine transitively pulls in the *old* `Theorizer.py` lineage that also backs the five
  `Evaluation*.py` modules. Star imports throughout.
- **No unit coverage below the capabilities.** Two test files total
  (`test_graceful_completion.py`, `test_memory_leak.py`); zero tests on any step executor.

**Deployed surface.** Only `asta.server:app` runs (`Dockerfile` CMD). `TheorizerServer.py` and
`TheorizerWebInterface.py` (Flask + pywebio) are legacy and not in the entrypoint — production is
A2A-only, so the plan's "back-end server + web server + programmatic endpoints" overstates it, and
Phase 0's instruction to inspect those two files points at the wrong lineage.

**The five stable seams** the A2A work left, commented `# --- Stable seams for the A2A layer ---`
(`Theorizer1.py:208-265`): `set_steps`, `seed_extraction_schema`, `seed_completed_extractions`,
`set_observer`, `from_persistence`. The `@asta.task` bodies reach the engine through these plus
`theorizer.submit_workflow`. Both adapters use the same six.

## Q2 — Theorizer state today

`Persistence.py` — a `PersistenceBackend` ABC with two implementations, selected by `DATABASE_URL`:

- `FilePersistence` (default): JSON under `data/{workflows,theorystores,paperstores}/`, plus an
  `ocr-cache/` tree and a file-backed kv.
- `PostgresPersistence`: JSONB tables `workflows`, `theorystores`, `paperstores`, `ocr_cache`,
  `kv_store`.

Three artifacts per run, all keyed by **`generation_id`** (not a session id):

1. **workflow dict** — parameters plus derived state (`theory_request_normalized`,
   `paper_search_query`, `extraction_schema`, `paper_keys`, `extraction_request_ids`,
   `completed_extraction_results`, `steps`, `current_step_idx`, timings, notes, errors, costs)
2. **theorystore dict** — `theories`, `extraction_schemas`, `extraction_results`,
   `theory_evaluations`, `all_ids`, `next_ids`
3. **paperstore dict** — papers including `paper_markdown` full text

**Granularity is whole-run, not per-artifact**, and writes are sparse: `save_workflow_to_file()` on
submit and completion, plus the `SAVE_THEORY_TO_DISK` step. **There is no per-step checkpoint** — a
mid-run crash loses everything since the last write.

Live in-run state is the in-memory god-object. `Theorizer.workflows_completed` is a bounded deque
(`MAX_COMPLETED_RETAINED`, default 20); eviction is safe because resume goes through persistence.

**Adjustment to §3.2 / §3.4.** Persistence is already an ArtifactStore in embryo — `put`/`get` keyed
by (kind, id), two backends. Missing: per-artifact handles, summaries, `list`, `update`, session
scoping. **Implement `ArtifactStore` as a facade over `Persistence`, not a parallel store.**
Correspondingly §3.4's "durability is entirely ours" is half wrong: durable storage and whole-run
resume (`from_persistence`) exist and are already exercised (`run_id` resume is a covered E2E case).
What's genuinely missing is **per-step checkpointing and an explicit awaiting-input state**. Scope
Phase 4 to those two.

## Q3 — PaperFinder coupling

**The plan's premise is wrong.** `SemanticScholar.get_paperfinder_results()` (`:561`) calls
`_get_paperfinder_results_internal()` (`:450`): an HTTP POST to
`https://prod-web.ai2i-agents.pandajungle.org/api/2/rounds`, then polls `<location>/enriched`. The
local variant (`localhost:8000`) is present but commented out at the dispatch site. Theorizer does
**not** depend on a local PaperFinder — it depends on a hardcoded production URL, with
`caller_actor_id: "test"` and `cost_trace_id: "test"` hardcoded in the request body, so PaperFinder
spend from Theorizer is untraced in prod. **Worth fixing regardless of this port.**

Coupling shape: `PaperFinderRequests` is a threaded queue with a global 2.5s inter-request throttle;
`submit_request()` → poll `get_work()`. The step then filters by knowledge cutoff and dedups via
`paperstore_lut`.

**Can curation move to asta-tools without behavior change? Not as scoped.** Two blockers:

1. The step does **search *and* full-text acquisition + OCR**. `find-literature` /
   `local-paper-index` / `semantic-scholar` cover search. The acquisition half
   (`PaperStore.submit_paper`, `MistralOCRStore`, the `ocr_cache` tables) has no library equivalent —
   `pdf-download` / `pdf-extraction` are SKILL.md skills, not callable libraries. Extraction and
   novelty both require OCR'd markdown, so dropping this half is a behavior change.
2. This repo's `find-literature` reaches PaperFinder **over A2A** (`src/asta/literature/client.py`).
   "One shared literature substrate in one process" is the *same* remote dependency behind a
   different client — which undercuts §3.7's claim that shared curation is a substantive argument for
   single-harness beyond avoiding the round-trip.

**Recommendation:** rescope §3.7 / Phase 6 to "share the *search* substrate; acquisition + OCR stay
Theorizer's," and confirm what `find-literature` actually returns first.

## Q4 — Hermes tool API

**Registration vs exposure: the separation exists, exactly as §3.6 hoped.**

- **Register** — `tools/registry.py`. `registry.register(name, toolset, schema, handler, check_fn=,
  requires_env=, max_result_size_chars=, dynamic_schema_overrides=, emoji=)`. Auto-discovery imports
  any `tools/*.py` with a top-level `registry.register()` call (AST-detected, `_module_registers_tools`).
- **Expose** — `toolsets.py`, a single `TOOLSETS` dict; `_HERMES_CORE_TOOLS` is the default bundle
  platforms inherit. AGENTS.md is explicit: *"auto-discovery imports the tool and registers its
  schema, but the tool is only exposed to an agent if its name appears in a toolset."*
- **Gate** — `check_fn` makes a tool appear only when a prerequisite is configured (zero schema
  footprint otherwise). This is the right mechanism for "only expose Theorizer tools when the
  gateway/credentials are configured."
- **Dynamic descriptions** — `dynamic_schema_overrides` (a zero-arg callable merged at
  `get_definitions()` time) lets a schema reflect runtime config. `delegate_task` uses it.

**Handle-only returns and the size guard already exist generically.** `tools/tool_result_storage.py`
implements a three-layer defense; §3.2's hand-rolled version is unnecessary:

1. per-tool self-truncation (tool author's job)
2. **per-result persistence** — a result over the tool's threshold is written to
   `{tmp}/hermes-results/{tool_use_id}.txt` and the in-context content is replaced with a
   ~1,500-char preview + file path the model can `read_file`
3. **per-turn aggregate budget** — 200K chars across all results in one assistant turn; the largest
   non-persisted results spill to disk until under budget

Thresholds resolve pinned → config override → registry per-tool → default, and scale to the model's
context window (`_PER_RESULT_WINDOW_FRACTION = 0.15`, `_PER_TURN_WINDOW_FRACTION = 0.30`, floor
8,000 chars). Defaults: `DEFAULT_RESULT_SIZE_CHARS = 100_000`, `DEFAULT_TURN_BUDGET_CHARS = 200_000`,
`DEFAULT_PREVIEW_SIZE_CHARS = 1_500`. **Caveat:** the registry per-tool value is capped at the
default, and plugin `ctx.register_tool()` does **not** accept `max_result_size_chars` — a
plugin-registered tool gets the default. Keep returning handles + summaries by construction; treat
the harness guard as a backstop, not the contract. AC#4 stays useful as our own test.

**No artifact/blob store for domain artifacts.** The plan's note ("the store is ours to build") is
correct. Nearest primitives: `hermes_state.py` `SessionDB` (SQLite + FTS5, WAL, conversation history
only) and kanban attachments (`kanban_attach` / `kanban_attach_url` / `kanban_attachments`, durable
SQLite board). Neither is a fit. Build the Q2 facade over Theorizer's own `Persistence`.

### The Footprint Ladder — this is the finding that reshapes Phase 3 and Phase 8

Two properties govern every Hermes design decision (AGENTS.md, "What Hermes Is"):

> **Per-conversation prompt caching is sacred.** Anything that mutates past context, swaps toolsets,
> or rebuilds the system prompt mid-conversation invalidates that cache.
>
> **The core is a narrow waist; capability lives at the edges.** Every model tool we add is sent on
> every API call, so the bar for a new *core* tool is high.

The Footprint Ladder ranks new capability, least footprint first: 1. extend existing code →
2. **CLI command + skill** → 3. service-gated tool (`check_fn`) → 4. **plugin** → 5. MCP server in the
catalog → 6. **new core tool (last resort)**.

Consequences the plan must absorb:

- **Registering six Theorizer tools into core `toolsets.py` is rung 6 and would be rejected
  upstream.** AGENTS.md's "what we don't want" list names *"plugins that touch core files"* and
  closes *"third-party products / other people's projects integrated into the core tree… They place
  an ongoing maintenance burden on us… Ship them as a standalone plugin repo users install into
  `~/.hermes/plugins/`."* An Ai2 Theorizer/autodiscovery integration is squarely that category.
  **Target: a standalone plugin repo, not a PR to hermes-agent.** The plugin surface is adequate —
  `register(ctx)` can call `ctx.register_tool(...)`, `ctx.register_cli_command(...)`, and lifecycle
  hooks (`pre/post_tool_call`, `pre/post_llm_call`, `on_session_start/end`).
- **Rung 2 is the ladder's default choice, and asta-plugins already occupies it.** Hermes loads
  SKILL.md and is agentskills.io-compatible, so `plugins/asta-tools/skills/generate-theories/SKILL.md`
  is close to portable as-is. Before building tool adapters, state what tools buy over the existing
  skill + CLI path — structured params/returns and machine callability are real answers, but they
  need to be argued.
- **§3.6's selective exposure is only valid at session boundaries.** Varying the exposed subset
  per-caller mid-conversation breaks prompt caching, which Hermes treats as inviolable. Rewrite AC#8
  as "distinct toolsets resolved at session/agent start," not runtime-switchable subsets.

## Q5 — Hermes sub-agent model

`tools/delegate_tool.py` (`delegate_task`) spawns child `AIAgent` instances with isolated context and
terminal session. Single (`goal` + optional `context`) or batch (`tasks: [...]`, concurrent).
`background=true` returns a delegation id immediately; the result re-enters via the async-delegation
completion queue. Roles: `leaf` (default — cannot `delegate_task`, `clarify`, `memory`,
`send_message`, `cronjob`; retains `execute_code`) and `orchestrator` (can re-delegate). Bounds under
`delegation:` in `config.yaml`: `max_concurrent_children` (3), `max_spawn_depth` (2),
`child_timeout_seconds`, `max_iterations`, `orchestrator_enabled`, `subagent_auto_approve`,
`inherit_mcp_toolsets`.

**Two facts that break §3.6 / Phase 7 as written:**

1. **The model has no `toolsets` argument.** `tools/delegate_tool.py:115-116`: *"nested delegation is
   granted by `role='orchestrator'`… NOT by the model naming toolsets — the model has no toolsets
   argument. Subagents inherit the parent's toolsets."* The Python signature accepts `toolsets` and
   the code narrows/expands it (`_expand_parent_toolsets`, `_preserve_parent_mcp_toolsets`), but the
   agent cannot choose. Granting a subagent a tool subset is a **config/code** decision, not a
   runtime one.
2. **A Hermes subagent is an LLM agent loop, not a process host.** Autodiscovery is a batch MCTS
   program (`run_mcts`, ~40 hyperparameters) with its own sandboxed code execution. It is not a thing
   you host as a subagent. Its correct Hermes rung is 2 (CLI + skill) — which is what
   `plugins/asta-tools/skills/autodiscovery/` + `src/asta/autodiscovery/` already do — or
   `terminal(background=True, notify_on_complete=True)` for a long run.

So "peer composition over one shared tool pool" is not the available shape. What *is* available: both
capabilities registered by one plugin into one Hermes instance, each reachable by the agent loop, with
the Theorizer→autodiscovery link made as a direct in-process Python call (see the autodiscovery
section), not as a tool call from inside autodiscovery.

## Q6 — Durability and async jobs

**Durable in Hermes:** `hermes_state.py` `SessionDB` (SQLite, FTS5, WAL, application-level write
retry with jitter) for conversations; `cron/jobs.py` + `cron/scheduler.py` for scheduled jobs
(duration / "every" phrase / 5-field cron / one-shot ISO, with a `.tick.lock` file lock against
duplicate ticks across processes); the kanban SQLite board for multi-worker task state.

**Not durable — stated explicitly.** AGENTS.md, Delegation:

> **Durability rule:** background `delegate_task` is detached from the current turn but still
> **process-local**. For work that must survive process restart, use `cronjob` or
> `terminal(background=True, notify_on_complete=True)` instead.

So §3.5's "enqueue a job, return a handle, poll status" **does** have a harness primitive, but the
one that matches (`background=true` delegation) is exactly the non-durable one. Two adjustments:

- **§3.5 maps to `terminal(background=True, notify_on_complete=True)`** — and for Theorizer this is
  *already the shape*: a long-running remote service invoked over HTTP, polled by the CLI. The
  existing `asta generate-theories … --no-wait` + poll path is Hermes-native. Phase 5 may be mostly
  "use the existing CLI in background mode," not "build a JobRunner."
- **Cron has a 3-minute hard interrupt on agent sessions.** Theorizer runs 15–25 min, and novelty
  adds 30–60 min. Cron cannot host a Theorizer run as an agent session; only a `no_agent=True`
  script job could, and it would need its own polling. Do not plan around cron for long runs.

**What we must own for suspend/resume:** everything domain-side. Hermes persists conversations, not
our artifacts, and its in-conversation async path is process-local. But per Q2, Theorizer already has
durable run storage and whole-run resume — so what we own is per-step checkpointing plus an
awaiting-input state, and the durable record must be Theorizer's `Persistence`, not Hermes session
state. §3.4's instinct ("never rely on in-memory session state for resume") is correct and now
verified against the code.

## Q7 — A2A adapter reuse

**Feasible, and cleaner than the plan assumes.** `src/asta/` is ~1,100 lines and already separated:
`server.py` (the six capability definitions), `context.py` (BYO injection), `workflow.py` (observer →
`AstaContext` bridge), `schemas.py`, `credits.py`, `artifacts/`. It touches the engine through exactly
the five documented seams plus `theorizer.submit_workflow`. Per Q1, the port is: lift `AstaContext` to
a Protocol, keep the six bodies, write a second implementation.

Two things the A2A adapter does that a Hermes adapter must also do — or explicitly drop:

1. **Progress + artifact streaming.** `AstaWorkflow` publishes per-theory / per-extraction /
   per-novelty-statement / per-paper artifacts *and* a single streaming Theory Store artifact assembled
   from RFC-7396 merge-patch fragments (`workflow.py:283-379`). This is the intermediate visibility
   that motivated the granular capabilities. Hermes has no artifact concept (Q4) — so this maps to
   files on disk plus terminal/tool output, and §2 goal 3 regresses unless that's designed for.
2. **Credits gating.** `credits.py` + `_run_via_queue` do an up-front `ctx.credits.check()` on an
   estimated paper count and a post-success `consume()` keyed by task id. This *is* the per-step cost
   control §7 asks for, it already exists, and it is bound to the A2A context. Hermes has no
   equivalent; re-home it or lose spend control on the most expensive capability in the system.

Debt to clean while re-homing: `workflow.py:250` `_emit_message` reaches into SDK-internal
`ctx._update_task_status` (already flagged `TECH DEBT` in-repo). Fold it into the Protocol as a first-
class `emit_message`.

**§6.2 is largely already built.** `tests/harness/e2e_matrix.py` + `run_e2e_matrix.sh` builds the
image, boots it, and exercises **every skill × every BYO input combination** in cost tiers
(cheap/medium/expensive) — including `run_id` resume, metadata-only hydration, `file://` URI paper
stores, `resume-extraction`, the full pipeline, and fail-fast validation. Use it as the AC#2 parity
baseline rather than writing new capture tests. It is also the *only* protection: unit coverage is two
files and no step executor is tested.

## Autodiscovery — bears on Q5, §3.6, Phase 7, AC#3, AC#8

- **No tool bus.** Its agents are AG2 `ConversableAgent`s in a group chat with a hardcoded
  `SpeakerSelector` (`transitions.py`) and structured-output `response_format`. `grep` across all of
  `packages/` for `register_for_llm`, `register_function`, `register_for_execution`, `tools=[]`
  returns **zero hits**. §3.6's "autodiscovery calls `theorizer_generate_theory(...)` as a tool"
  cannot be delivered by exposing tools to it. Combined with Q5 (`delegate_task` has no model-facing
  `toolsets`), the "shared tool pool" framing does not survive contact with either codebase.
- **Recommended Phase 7 shape:** a callback parameter on `run_mcts` invoked at the surprisal branch
  (`run.py:266-278`, where `all_surprisals.append((node.level, node.node_idx))`), calling the
  Theorizer core function directly in-process. Small, testable, matches the real control flow, needs
  no tool bus, and keeps the plan's own non-goal ("do not rewrite autodiscovery's control policy")
  intact. Introducing AG2 tool registration would violate that non-goal.
- **AC#3 already passes.** `grep -rn "a2a" packages/` → zero hits. A2A appears only in
  `api/runs/runs_api.py` (fires `message/send` to Asta DataVoyager) — the web API layer, not the
  discovery loop. The port is not *removing* existing intrusiveness; it is choosing how to add a
  Theorizer↔autodiscovery link that does not exist yet. §1 should be reframed as prospective.
- **Code execution is already out-of-process by design** (`backend` ∈ `local`/`process`/`modal`,
  `ModalSandboxExecutor`, GCS bucket paths, per-cell `uv` installs). One harness process does not
  collapse this, and shouldn't try.
- **Packaging conflict — should gate the approach.** autodiscovery: `requires-python >=3.13`,
  `ag2[openai,gemini]==0.10`, `matplotlib==3.10`. Theorizer: **`python:3.12-slim`**,
  `litellm==1.60.5`, `numpy==2.2.6`, and a **vendored `mistralai` wheel because the package is
  quarantined on PyPI** (`Dockerfile:5-7`). asta-plugins: `>=3.11`. Hermes: Python 3.11 per its
  installer. Co-hosting in one process is a four-way reconciliation including a package not
  installable from PyPI. This argues for keeping both behind process boundaries (HTTP/CLI) and making
  the *plugin* the only shared address space — which is also what the Footprint Ladder wants.

## The existing SKILL.md path is not an alternative — it *is* the thing being removed

`generate-theories/SKILL.md` does implement piecemeal choreography (automatic-vs-piecemeal mode
selection, continue/stop/edit between stages, resume by `task_id`), but it achieves every stage
boundary **by making an A2A call**: SKILL.md → `asta generate-theories <subcommand>` →
`make_a2a_group` (`src/asta/theorizer.py`) → HTTP/JSON-RPC via asta-gateway → `@asta.task` handler.
The stage seams exist only as A2A round-trips. That is precisely the internal composition bus §1
names, so "port the SKILL.md and stop" would preserve the problem rather than solve it. Treat the
skill path as the *baseline being replaced*, not as a competing option.

**The requirement is therefore in-process:** the six capabilities must be callable as Python
functions inside the harness process, with A2A retained only at the perimeter for external callers.
Target rung: **plugin** (settled — no core Hermes changes). Two consequences follow, and they are the
real cost of the port.

### In-process makes the dependency conflict binding, not advisory

Finding #3 stops being a caution the moment "in-process" is the goal. A Hermes plugin lives in the
Hermes interpreter (Python 3.11 per its installer). Importing Theorizer's core there means importing
`Theorizer1.py` and, transitively, the whole legacy `Theorizer.py` lineage plus `litellm==1.60.5`,
`numpy==2.2.6`, `psycopg2-binary`, and a **`mistralai` wheel that must be vendored because the
package is quarantined on PyPI**. Theorizer's own container is `python:3.12-slim`. Either that
reconciles against Hermes 3.11, or the core does not load in-process and the port cannot deliver its
premise. **Resolve this before Phase 1** — it is the one finding that can invalidate the shape.

(Autodiscovery is unaffected: it stays out-of-process behind CLI/`terminal`, reached from Theorizer
by the `run_mcts` callback. Only Theorizer's core needs to be importable.)

### The core must become import-side-effect-free

Today, importing the entry module *starts a thread farm*. `src/asta/server.py:44-45` runs
`loadAPIKeys()` and `theorizer = Theorizer()` at module scope, and that constructor
(`Theorizer1.py:1765-1811`) creates `data/`, a global `PaperStore` (whose `__init__` calls
`start_thread()`), its own worker thread, and five `StepProcessor`s — each holding a
`ThreadPoolExecutor(max_workers=5)`, one of which constructs `PaperFinderRequests()` (another
thread). `Theorizer1.py:47` also does a module-level `os.makedirs(DEBUG_OUTPUT_DIR)`, and
`SchemaExtractionQueue.__init__` starts another thread per extraction.

This matters because Hermes runs `discover_plugins()` as a side effect of importing
`model_tools.py` — i.e. on ordinary CLI invocations, not just when a Theorizer tool is called. A
plugin that imports the core at module scope would spin up ~30 threads and create directories on
every `hermes` command.

**Mitigation, and a Phase 1 acceptance criterion:** the plugin's `register(ctx)` must register only
thin handlers; the core is lazy-imported inside the handler on first call, and the `Theorizer`
engine is constructed behind a lazily-initialized singleton with explicit shutdown wired to the
`on_session_end` hook. Add a test asserting that importing the plugin module starts no threads and
creates no directories.

---

## Proposed adjustments, ranked

1. **Retarget Phase 1/Phase 3 to the `@asta.task` boundary.** Lift `AstaContext` to a Protocol (the
   ~10 members listed in Q1), move the six bodies to `core/`, implement the Protocol twice. Delete
   §3.1's `generate_schema(goal, corpus, store)` sketch and the `core/theorizer/steps.py` layout —
   no step-executor refactor.
2. **Ship as a standalone Hermes plugin repo installed into `~/.hermes/plugins/`.** Not a PR to
   hermes-agent, not core `toolsets.py`. Hermes's own rubric closes in-tree third-party integrations
   and ranks new core tools last. Use `register(ctx)` + `ctx.register_tool` + `check_fn` gating —
   with thin handlers and a lazy-imported core (see "The core must become import-side-effect-free").
3. **Resolve the Theorizer-in-Hermes dependency conflict before Phase 1** — this is now a blocker,
   not a caution. In-process is the whole premise, so Theorizer's core must import into the Hermes
   interpreter (3.11) despite its 3.12 container, pinned `litellm`/`numpy`, and PyPI-quarantined
   `mistralai` wheel. Autodiscovery stays out-of-process behind CLI/`terminal`.
4. **Rewrite Phase 7 as a `run_mcts` surprisal callback**, and reframe §1's motivation as prospective
   (autodiscovery has no A2A today, so AC#3 passes as-is).
5. **Delete the bespoke ArtifactStore-plus-size-guard work in §3.2**; keep handle+summary returns as
   a construction discipline, rely on `tool_result_storage.py` as backstop, and build the store as a
   facade over Theorizer's `Persistence` (Q2). Note plugin-registered tools can't set
   `max_result_size_chars`.
6. **Re-home credits gating and progress/artifact streaming explicitly** — both exist, both are
   A2A-context-bound, Hermes has no equivalent for either, and losing either regresses a stated goal.
7. **Fix the step list in §3.1/§3.3** to the six live steps; drop `curate corpus` and `reflect`; add
   `save` and `novelty`; note the two dead steps.
8. **Correct the PaperFinder premise** and rescope §3.7 / Phase 6 to search-only sharing.
9. **Rewrite §3.5/Phase 5 around `terminal(background=True, notify_on_complete=True)`**, note that
   `background` delegation is process-local, and do not plan long runs on cron (3-minute interrupt).
10. **Rewrite AC#8** as distinct toolsets resolved at session/agent start — prompt caching forbids
    mid-conversation toolset swaps, and `delegate_task` gives the model no `toolsets` argument.
11. **Scope Phase 4** to per-step checkpointing + an awaiting-input state over the existing durable
    `Persistence`, not durability from scratch.
12. **Reuse `tests/harness/e2e_matrix.py` as the AC#2 baseline**, and add unit tests at the
    `@asta.task` level before refactoring — there is currently no coverage below the E2E matrix.
13. **Add an import-hygiene acceptance criterion** — importing the plugin module starts no threads
    and creates no directories; the engine initializes lazily on first tool call and shuts down via
    `on_session_end`. Required because Hermes discovers plugins on every CLI invocation.
14. **Retire `generate-theories/SKILL.md`'s A2A stage calls as part of Phase 3**, and record its
    current behavior as the UX baseline the in-process path must match (mode selection,
    continue/stop/edit, resume). It is the artifact being replaced, so its choreography is a
    requirement to preserve, not evidence the work is already done.
