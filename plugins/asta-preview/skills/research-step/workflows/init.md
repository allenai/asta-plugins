# Workflow: init

Bootstrap the environment for a research session: install `bd` and `jq`, run `bd init`, and verify the staleness check works. This is the only workflow that may install or configure tools; `plan`, `update-summary`, and `execute` assume the environment is ready.

After environment setup, hand off to **plan** to bootstrap the mission epic and initial frontier.

## Preconditions

None. `init` is idempotent — installing already-installed tools is a no-op, and `bd init` is safe to skip if `.beads/` already exists.

## Steps

1. **Ensure `bd` is installed.**
   - Run `command -v bd`. If present, skip.
   - Otherwise, install per the beads project's documented method for the current platform. Consult https://github.com/gastownhall/beads (cross-platform options at time of writing include `go install`, Homebrew, `winget`, the project's install script, and the Nix flake). If you are uncertain which method applies, fetch the install docs at run time rather than guessing.
   - Verify with `bd --version`. If it still fails, abort and ask the user to install manually.

2. **Ensure beads is initialized in this directory.**
   - If `.beads/` does not exist, run `bd init`.
   - Verify with `bd list` (should succeed and return an empty list or existing issues).
   - Register the `failed` custom status used by the autods-to-theorizer template's failure path:
     `bd config set status.custom "failed:done"`. Idempotent — safe to re-run.
     Confirm with `bd statuses` (should list `failed` under "Custom statuses").

3. **Verify the staleness check works.**
   - Run `scripts/summary-check.sh`. It hashes the sorted IDs of currently-open issues and compares against `summary.md`'s frontmatter. Backend-agnostic — beads can use whichever storage it likes.
   - Requires `jq` on PATH; if missing, install it (`brew install jq`, `apt-get install jq`, etc.) and retry.
   - At init time `summary.md` does not yet exist, so the script will print `status: missing` and exit 1 — that's fine; **update-summary** will create the file later. `status: no-tools` (exit 3) means abort and ask the user.

4. **Hand off to plan.** Per the router's chaining rule, run the **plan** workflow next. It will detect that no epic exists yet and bootstrap one from `mission.md`. If `mission.md` is missing, **plan** will route the user back to **brainstorm**.

## Out of scope for this workflow

- Creating issues or building the graph. That belongs to **plan**.
- Writing `summary.md`. That belongs to **update-summary** (chained automatically after `plan`).
- Re-running setup once a session is initialized. If `bd` or `jq` breaks later, fix it manually rather than re-running `init`.
