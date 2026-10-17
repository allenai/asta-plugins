# Changelog

## Unreleased

- Add `asta workspace overleaf check` for an opt-in live round trip on a
  scratch pair reserved for checks: merge co-author edits after GitHub checks,
  publish a workspace edit, then resolve and merge a conflict, moving the pair
  forward. A recent check in progress makes the pair busy; a stale one's
  leftovers are cleared. Release preserves a replacement owner's lock, and the
  timeout (including acquisition) stays below the stale-lock threshold. The
  command waits within one invocation and refuses CI. An explicitly empty
  `sync --check-repo` value refuses sync instead of disabling the release gate.
