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

## Threat model

The checks below catch accidents and stale state, so that an Overleaf edit is
neither skipped nor overwritten: a wrong or hand-edited `base`, a concurrent
pull or publish, a stale or shallow clone, an interrupted publish, or a record
that no longer matches reviewed history. They also keep a workspace writer who
cannot merge to the default branch, or an Overleaf collaborator acting alone,
from moving the sync point.

They are not a defence against forgery. Someone who can write to both the
workspace repository (including `refs/asta/overleaf/*`) and the Overleaf project
can construct matching history and records that make an edit count as synced,
including a record that attests an older reviewed paper. That stays out of
scope. Sync also publishes whatever reaches the default branch, so review of
paper changes rests on the default branch's protection rules, not on the CLI.

## Sync point

The sync point is the record's Overleaf commit when it is in Overleaf history
and descends from `base`; otherwise it is `base`. Publish proceeds only when
Overleaf's head equals it. Pull merges against that commit's files, except in a
checkout that neither contains the record's workspace commit nor already has its
paper: there it merges from `base`, so the published edits arrive for review
instead of being skipped.

Readers trust a record only when it matches reviewed history: its workspace
commit must be an ancestor of `origin`'s default-branch tip, and its Overleaf
commit's files must equal that commit's `paper/` files, ignoring
`paper/overleaf.json`. Files are compared by content, because Overleaf and the
workspace may use different hash functions. Otherwise pull warns and uses
`base`, so edits since that pull arrive for review; publish refuses until a
maintainer restores or deletes the rejected record. A workspace writer who cannot
merge to the default branch therefore cannot move the sync point to unreviewed
content, and Overleaf access alone cannot move it either.

A record must also continue from the record it was written over: its workspace
commit descends from that record's workspace commit, and its Overleaf commit has
exactly one parent, the previous sync point. That point is the preceding record's
Overleaf commit, or a newer committed pull's `base` in the published workspace
commit (already covered by the current verified base). Later pulls do not change
that publication's parent. An attested merge or a gap containing other Overleaf
edits is rejected even when its tree matches reviewed content. A record with no
parent must be the first publication since `paper/overleaf.json`'s `base` (its
Overleaf commit has exactly one parent, `base`), and its workspace commit must
descend from the default-branch commit that last changed `paper/overleaf.json`
along the default branch's first-parent
history (the same history used to check base moves). Otherwise pull warns and uses
`base`, so a record attesting an older reviewed paper cannot make an Overleaf
revert count as synced. Publish refuses a rejected record before pushing, even
after a recovery pull has advanced `base`: it must not append to an invalid chain.
A maintainer must restore the record ref from its history or delete it, then pull
and review any remaining Overleaf edits before publishing.

Verification walks predecessors back to the first record whose Overleaf commit
is already included in the committed `base`. Earlier publication sources do not
need to be present or reverified: the committed pull accounts for those edits.
The newest record is always checked. Between pulls, the work grows linearly with
the number of publications since `base`; shallow clones need those workspace
sources and their ancestry. A pull committed to the default branch advances the
checkpoint. Checking only the immediate parent would let a writable intermediate
record hide an earlier rollback. Rewriting default-branch history may invalidate
records, requiring the same maintainer repair.

## Failure handling

Refusals are one line with a concrete action and a link to the workspace skill's
[recovery reference](../plugins/asta-tools/skills/workspace/workflows/overleaf-recovery.md).
Checking base moves needs the first-parent config history back to this project's
initial import, including each config-changing commit's parent. This is independent
of the publication-record checkpoint above: a later valid base move cannot establish
that an earlier move imported its edits. A shallow clone lacking this history refuses,
even when its paper equals the current tip; explicitly fetch workspace history and
retry. Sufficiently deep shallow clones still work without changing their boundary.

- Pull and publish check every effective move of `base` in `paper/overleaf.json`
  since this project's initial import. Every file Overleaf changed between a move's
  old and new `base` must hold Overleaf's new version, be changed by that commit, or
  be a conflict resolved by keeping the workspace's text (both sides had edited it).
  A later move importing another file cannot hide an earlier omission. An explicit
  rewind cancels advances beyond the restored base so a recovery pull can import
  those edits; omissions before that base still refuse. Errors name the offending
  commit, file and old `base`; recovery is in `workflows/overleaf-recovery.md`.
- Sync does not check how a commit reached the default branch: it publishes the paper
  that is there. A repository that wants every paper change reviewed must require PRs
  on its default branch.
- After pushing, publish fetches Overleaf's head and requires it to descend from
  the prior sync point. If it also descends from the pushed commit, publish records
  that pushed commit, leaving any later collaborator edits for the next pull.
  Otherwise it records the head only when it has exactly one parent equal to the
  prior sync point and its tree matches the pushed commit, allowing a bridge to
  translate that commit without concealing other edits. An unrelated
  same-tree replacement is refused. A translated commit followed by further edits
  cannot be confirmed by either check and still needs recovery. If confirmation
  or the record push fails, publish exits 1 after the Overleaf push without
  advancing the record. When Overleaf still descends from `paper/overleaf.json`'s
  base and has no further collaborator edits, pull imports the published files
  matching the workspace, so its PR changes only `paper/overleaf.json`. Later
  collaborator edits are also imported for review. If that history was reset,
  restore it before pulling or publishing again.
- The record push skips pre-push hooks (`--no-verify`): branch hooks do not
  apply to this metadata ref. A remote policy that rejects
  `refs/asta/overleaf/*` can still stop the record push after Overleaf has
  accepted the paper; the same pull-and-PR recovery applies.
- Pull refuses, with nothing copied, if `origin` exists but the record cannot be
  read or reviewed history cannot be fetched. Falling back to an older base can
  silently undo a deliberate workspace revert of a previously published edit:
  when the reverted file equals that base, the published Overleaf bytes appear
  to be a one-sided change. Refusing avoids copying before the current record
  can be checked. Retry once origin access or its default branch is restored.
  With no `origin` remote, pull warns and uses `base` alone; that compatibility
  path cannot verify publications made from other clones.
- A shallow checkout refuses when the record's workspace commit is missing or
  its ancestry cannot be verified, either against origin's default tip or the
  checkout's own history. A shallow boundary can hide a reviewed publication;
  treating it as unreviewed or unseen and falling back to `base` could undo a
  workspace revert. Fetch the workspace history from `origin` explicitly and
  retry (for example, `git fetch --unshallow origin`). Both commands refuse
  before copying or pushing; dry-run also refuses. The CLI never deepens history
  automatically. Shallow checkouts with verifiable ancestry still work normally,
  as does pull when the checkout's paper already matches the trusted record.
- An invalid record refuses both commands before copying files or pushing to
  Overleaf. This includes every predecessor consulted before the base checkpoint:
  its JSON, full commit IDs and project URL have the same validation as the tip.
  A missing or malformed predecessor is not treated as a parentless first record.
  The ref must point directly to a commit; trees and tags are invalid,
  even with a valid `sync.json`. Restore the ref from its history or delete it
  to fall back to `paper/overleaf.json`.
- A record whose Overleaf commit is missing from Overleaf history produces a
  warning and falls back to `base`.

Fetching the record uses a temporary ref and transfers only record commits, so
shallow workspace history and existing refs are unchanged. Publish keeps that
ref until it has pushed the next record, protecting the previous parent from
garbage collection, then removes it on success or failure.

## Hosted evidence

The hosted bridge preserved the subjects of two CLI-published commits beneath a
later web edit in a fresh clone
([PR comment](https://github.com/allenai/asta-plugins/pull/204#issuecomment-6134939707)).
That check predates the record ref; the tree comparison above covers a bridge
that rewrites pushed commit IDs.
