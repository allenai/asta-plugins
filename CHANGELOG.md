# Changelog

## Unreleased

- Add `asta workspace overleaf check` for an opt-in live round trip on a
  disposable scratch pair: merge co-author edits after GitHub checks, publish a
  workspace edit, resolve and merge a conflict, then restore paper contents and
  sync metadata. The command waits within one invocation and refuses CI.
- Keep regular sync runs out of a scratch pair while its release check owns it.
