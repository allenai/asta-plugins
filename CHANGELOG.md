# Changelog

## Unreleased

- Add `asta workspace bump-pin`: when `.github/workflows/docs.yml` pins a
  release older than the installed asta's final release, commit a move of the
  pin to that release as its own commit. The workspace skill runs it before an
  agent opens a PR and drops the commit if the bump breaks the build.
- Add `asta workspace overleaf check` for an opt-in live round trip on a
  scratch pair reserved for checks: merge co-author edits after GitHub checks,
  publish a workspace edit, then resolve and merge a conflict, moving the pair
  forward. A recent check in progress makes the pair busy; a stale one's
  leftovers are cleared. Release preserves a replacement owner's lock, and the
  timeout (including acquisition) stays below the stale-lock threshold. The
  command waits within one invocation and refuses CI. An explicitly empty
  `sync --check-repo` value refuses sync instead of disabling the release gate.
