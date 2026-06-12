# Workflow: init

Bootstrap the environment for a research session: install `bd`, `jq`, PyYAML, and jsonschema, run `bd init`, wire beads to the project's git remote for cross-machine sync, and verify the staleness check works. This is the only workflow that may install or configure tools; `plan`, `update-summary`, and `execute` assume the environment is ready.

After environment setup, hand off to **plan** to bootstrap the mission epic and initial frontier.

## Preconditions

None. `init` is idempotent — installing already-installed tools is a no-op, and `bd init` is safe to skip if `.beads/` already exists.

## Backend choice

`init` always uses beads' embedded Dolt backend (`bd init`, no `--server`). This satisfies the single-machine workflow with zero infrastructure. Cross-machine transfer is handled via `bd dolt push`/`pull` against the project's git remote (under `refs/dolt/*`) — git is the only sync layer.

Server mode (`bd init --server`) is out of scope: it requires running a Dolt sql-server, which violates the zero-infrastructure constraint. Simultaneous writers on multiple machines are therefore unsupported; the model is one writer at a time, with git as the transfer medium.

## Steps

1. **Ensure `bd` is installed.**
   - Run `command -v bd`. If present, skip.
   - Otherwise, install per the beads project's documented method for the current platform. Consult https://github.com/gastownhall/beads (cross-platform options at time of writing include `go install`, Homebrew, `winget`, the project's install script, and the Nix flake). If you are uncertain which method applies, fetch the install docs at run time rather than guessing.
   - Verify with `bd --version`. If it still fails, abort and ask the user to install manually.

2. **Initialize beads (embedded Dolt) and wire it to git.**
   - If `.beads/` does not exist, run `bd init`.
   - If the working directory has a git remote `origin`, configure beads' Dolt sync against it so `bd dolt push`/`pull` work without further setup. Probe with `bd dolt remote list`; if nothing is configured, add a remote pointing at `origin` per beads docs.
   - If no git remote exists, skip the Dolt-remote step and tell the user that cross-machine transfer will need a remote added later. Do not block — the single-machine flow works without it.
   - Verify with `bd list` (should succeed and return an empty list or existing issues).

3. **Fresh-clone recovery.** If `bd init` produced an empty DB but `.beads/issues.jsonl` is present (the project had upstream beads state and was freshly cloned), **do not silently `bd import`**.
   - Run `git ls-remote origin 'refs/dolt/*'`. If any Dolt refs exist, run `bd dolt pull` — this is the canonical recovery path and preserves Dolt history.
   - If no Dolt refs exist on the remote, surface the situation to the user with three options: (a) `bd import .beads/issues.jsonl` (fast, but discards Dolt history and any state newer than the export), (b) configure a Dolt remote and `bd dolt push` from another machine that has the live DB, then retry, (c) abort.
   - Pick one path only after explicit user confirmation. Never auto-import.

4. **Ensure `python3` can import `yaml` (PyYAML) and `jsonschema`.** `scripts/task-output-keys.sh` (used by `create-task.sh` and `validate-output.sh`) parses `assets/schemas.yaml` with PyYAML; `validate-output.sh` deep-validates each task's `output_json` against the compiled schemas in `assets/compiled/` with jsonschema, and hard-fails (exit 5) without it.
   - Probe with `python3 -c 'import yaml, jsonschema'`. If it succeeds, skip.
   - Otherwise install what's missing: `python3 -m pip install --user pyyaml jsonschema` (or the platform equivalent, e.g. `apt-get install python3-yaml python3-jsonschema`). Re-probe; if it still fails, abort and ask the user.

5. **Verify the staleness check works.**
   - Run `scripts/summary-check.sh`. It hashes the sorted IDs of currently-open issues and compares against `summary.md`'s frontmatter. Backend-agnostic — beads can use whichever storage it likes.
   - Requires `jq` on PATH; if missing, install it (`brew install jq`, `apt-get install jq`, etc.) and retry.
   - At init time `summary.md` does not yet exist, so the script will print `status: missing` and exit 1 — that's fine; **update-summary** will create the file later. `status: no-tools` (exit 3) means abort and ask the user.

6. **Hand off to plan.** Per the router's chaining rule, run the **plan** workflow next. It will detect that no epic exists yet and bootstrap one from `mission.md`. If `mission.md` is missing, **plan** will route the user back to **brainstorm**.

## Cross-machine transfer

To move a session to another machine:

1. On machine A: `bd dolt push` (sends the Dolt data as a git ref to `origin`).
2. On machine B: clone the repo and run this `init` workflow. Step 3's fresh-clone recovery will see the Dolt refs on `origin` and `bd dolt pull` them automatically.

Two machines writing at the same time is not supported in embedded mode; coordinate manually (push before handing off, pull before resuming).

## Out of scope for this workflow

- Creating issues or building the graph. That belongs to **plan**.
- Writing `summary.md`. That belongs to **update-summary** (chained automatically after `plan`).
- Re-running setup once a session is initialized. If `bd` or `jq` breaks later, fix it manually rather than re-running `init`.
- Server-mode beads (`bd init --server`) and any setup requiring a running Dolt sql-server.
