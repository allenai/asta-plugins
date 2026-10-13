# Overleaf sync point

`asta workspace overleaf pull` and `publish` need the last Overleaf commit whose
content the workspace already reviewed. Two records in the workspace repository
supply it; Overleaf history is never trusted to name one.

- `paper/overleaf.json` holds `url` and `base`, the Overleaf commit of the last
  pull. It lands through the pull's reviewed PR.
- `refs/asta/overleaf/<project-id>` on `origin` is written by publish after a
  successful Overleaf push. Each record is a commit whose tree holds `sync.json`
  with `url`, `overleaf` (the resulting Overleaf commit) and `workspace` (the
  published default-branch commit, SHA-1 or SHA-256). Its parent is the previous
  record, so the push is a fast-forward and a concurrent publisher's record is
  never overwritten.

The sync point is the record's Overleaf commit when it is in Overleaf history
and descends from `base`; otherwise it is `base`. Publish proceeds only when
Overleaf's head equals it. Pull merges against that commit's files, except in a
checkout that neither contains the record's workspace commit nor already has its
paper: there it merges from `base`, so the published edits arrive for review
instead of being skipped.

Moving the sync point therefore needs write access to the workspace repository.
An Overleaf collaborator can still edit anything, but those edits always reach
the workspace through pull and review.

## Failure handling

- After pushing, publish fetches Overleaf's head and records it only when it
  descends from the prior sync point and is the pushed commit or has the same
  tree. A bridge can translate the pushed commit while retaining that history;
  an unrelated same-tree replacement is refused. Otherwise, or if the record
  push fails, publish exits 1 after the Overleaf push without advancing the
  record. When Overleaf still descends from `paper/overleaf.json`'s base, pull
  imports the published files as Overleaf edits matching the workspace, so its
  PR changes only `paper/overleaf.json`. If that history was reset, restore it
  before pulling or publishing again.
- Pull refuses, with nothing copied, if `origin` exists but the record cannot be
  read, and warns and uses `base` alone when there is no `origin` remote.
- An invalid record refuses both commands. Restore the ref from its history or
  delete it to fall back to `paper/overleaf.json`.
- A record whose Overleaf commit is missing from Overleaf history produces a
  warning and falls back to `base`.

Fetching the record uses a temporary ref and transfers only record commits, so
shallow workspace history and existing refs are unchanged.

## Hosted evidence

The hosted bridge preserved the subjects of two CLI-published commits beneath a
later web edit in a fresh clone
([PR comment](https://github.com/allenai/asta-plugins/pull/204#issuecomment-6134939707)).
That check predates the record ref; the tree comparison above covers a bridge
that rewrites pushed commit IDs.
