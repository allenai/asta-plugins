# Overleaf sync point

The sync uses Overleaf's Git integration, not its GitHub synchronization; see
Overleaf's "Git integration and GitHub synchronization" documentation.

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

## Shared format and releases

`FORMAT` in `src/asta/commands/overleaf.py` versions the config, publication
record, lock commit and managed sync PR header together. Unversioned state is
format 1. Bump the format only when an older reader would misinterpret the state;
additive changes that old readers can safely ignore do not need a bump.
`FORMAT_RELEASE` names the first asta release that understands that format.

Before releasing a new format, verify that `FORMAT_RELEASE` matches the first
release shipping its reader. The initial format-aware release is planned as
0.116.0; if that changes, update the constant and the workspace developer and
recovery guides in the release PR. Older releases ignore stamps entirely, so
every runner must adopt the first format-aware release before the format can
increase. Keep the release hint for an existing format unchanged in later
compatible releases.

## Threat model

The checks catch stale or damaged records and stale clones: a concurrent pull or
publish, a shallow clone hiding a publication, an interrupted publish, or a record
that is damaged or no longer matches the default branch. They do not establish
whether a manually chosen sync point includes every co-author edit.

`base` is trusted as committed on the default branch. This gives up protection
against a hand edit to `base`, or a hand-written record, that moves the sync point
past an Overleaf edit: a pull can then skip a co-author's edit. In exchange, no
unusual but legitimate history (such as a `base` set by an older version) can leave
the sync refusing on every run. Overleaf keeps every edit, so a skipped edit is
recoverable: the [recovery reference](../plugins/asta-tools/skills/workspace/workflows/overleaf-recovery.md#recovering-a-skipped-co-author-edit)
says how to find it in Overleaf's history and bring it back. Sync also publishes
whatever reaches the default branch, so review of paper changes rests on the
default branch's protection rules, not on the CLI.

## Sync point

A record counts when its ids are full commit ids, its workspace commit is an
ancestor of `origin`'s default-branch tip, and its Overleaf commit's files equal
that commit's `paper/` files, ignoring `paper/overleaf.json`. Files are compared by
content, because Overleaf and the workspace may use different hash functions.

The sync point is a counting record's Overleaf commit when it is in Overleaf
history and descends from `base`; otherwise it is `base`. When a record exists but
does not count, pull prints `Overleaf sync record not used: <reason>. Pull started
from overleaf.json's base`, so `sync` can pass the reason on. Starting from `base`
can produce conflicts; preserving edits depends on the trusted base being correct.
If `base` itself is unreadable or not
in Overleaf history, pull starts from a counting record; with none, it refuses and
asks for `base` to be set, in a PR, to an Overleaf commit the default branch already
has. Publish proceeds only when Overleaf's head equals the sync point.

## Failure handling

Refusals are one line with a concrete action and a link to the workspace skill's
[recovery reference](../plugins/asta-tools/skills/workspace/workflows/overleaf-recovery.md).
Every remaining refusal names a fix that works.

- Sync does not check how a commit reached the default branch: it publishes the paper
  that is there. A repository that wants every paper change reviewed must require PRs
  on its default branch.
- After pushing, publish fetches Overleaf's head and requires it to descend from
  the prior sync point. If it also descends from the pushed commit, publish records
  that pushed commit, leaving any later collaborator edits for the next pull.
  Otherwise it records the head only when its tree matches the pushed commit,
  allowing Overleaf's Git integration to translate that commit. An unrelated
  same-tree replacement is refused. A translated commit followed by further edits
  cannot be confirmed by either check and still needs recovery. If confirmation
  or the record push fails, publish exits 1 after the Overleaf push without
  advancing the record. When Overleaf still descends from `paper/overleaf.json`'s
  base and has no further collaborator edits, pull imports the published files
  matching the workspace, so its PR changes only `paper/overleaf.json`. Later
  collaborator edits are also imported for review. If that history was reset,
  use the [base recovery steps](../plugins/asta-tools/skills/workspace/workflows/overleaf-recovery.md#base-not-in-overleaf-history)
  before pulling or publishing again.
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
- A damaged record (invalid JSON, short ids, a different project URL, or a ref
  that is not a commit) makes pull start from `base` and say why. Publish refuses
  only a ref that is not a commit, because a fast-forward push cannot replace it;
  restore the ref from its history or delete it.
- A record whose Overleaf commit is missing from Overleaf history produces a
  warning and falls back to `base`.

Fetching the record uses a temporary ref and transfers only record commits, so
shallow workspace history and existing refs are unchanged. Publish keeps that
ref until it has pushed the next record, protecting the previous parent from
garbage collection, then removes it on success or failure.

## Hosted evidence

Overleaf's hosted Git integration preserved the subjects of two CLI-published commits beneath a
later web edit in a fresh clone
([PR comment](https://github.com/allenai/asta-plugins/pull/204#issuecomment-6134939707)).
That check predates the record ref; the tree comparison above covers Git
integration rewriting pushed commit IDs.
