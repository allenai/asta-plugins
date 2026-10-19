# Changelog

## Unreleased

- Add `asta workspace bump-pin`: when `.github/workflows/docs.yml` pins a
  release older than the installed asta's final release, commit a move of the
  pin to that release as its own commit. The workspace skill runs it before an
  agent opens a PR and drops the commit if the bump breaks the build.
- Add `asta workspace overleaf sync --wait SECONDS` for papers synced by hand:
  one call reruns sync through checks, the quiet merge run and another run's
  recent lock until it completes or a person must act, bounded by the deadline.
  Checks not yet visible keep waiting; the shared deadline prevents starting
  retries or later papers, while an attempt already running finishes normally.
  It ends with one `Sync outcome:` line and exits 0 complete, 4 a person must
  act, 5 still waiting (rerun resumes), 1 an operator must act. Plain `sync`
  for scheduled runners is unchanged. The workspace docs say when to sync by
  hand and when a scheduled runner is worth it.
- Add `asta workspace overleaf check` for an opt-in live round trip on a
  scratch pair reserved for checks: merge co-author edits after GitHub checks,
  publish a workspace edit, then resolve and merge a conflict, moving the pair
  forward. A recent check in progress makes the pair busy; a stale one's
  leftovers are cleared. Release preserves a replacement owner's lock, and the
  timeout (including acquisition) stays below the stale-lock threshold. The
  command waits within one invocation and refuses CI. An explicitly empty
  `sync --check-repo` value refuses sync instead of disabling the release gate.
