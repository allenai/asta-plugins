# Overleaf sync point

The sync uses Overleaf's Git integration, not its GitHub synchronization; see
Overleaf's "Git integration and GitHub synchronization" documentation.

## Check a release on a scratch pair

Before adopting a new CLI release, reserve a **disposable scratch Overleaf
project and its paired scratch repository**, then run:

```sh
asta workspace overleaf check --project /path/to/scratch-checkout
```

This command writes to both sides. Reserve the scratch pair exclusively, with
no collaborators, scheduled syncs or other default-branch writers during the
check. Start with matching nonempty paper contents
and the current default branch's committed `paper/overleaf.json`. Close any open
sync PR first. A leftover sync-created `asta/overleaf-sync/<project-id>` branch
is saved and restored; unrelated work on that reserved branch is refused.
The Git identity and existing Overleaf/GitHub authentication are the same as for
`sync`. The scratch repository must allow the check to push test and restoration
commits to its default branch, open/close PRs, and merge through the normal sync
path after checks pass. It must have at least one successful check and no
unsatisfied review requirements. The command does not disable repository rules
or supply approvals. A protected paper repository is not a scratch target.

One call creates a uniquely named paper source on Overleaf, brings it through
the sync PR and merges it, publishes a workspace edit, creates a conflict on
that file, resolves it on the sync branch, waits for that head's checks, and
merges/publishes the resolution. It calls the released `sync` and `publish`
implementation, including their normal check and merge decisions. It polls
GitHub while checks run and reruns sync once they pass; it never leaves an
unfinished check for the next schedule as part of normal operation.

After acquiring the check lock, the command refuses any default-branch commit
that appeared during preflight, including changes outside the paper and commits
that leave the files unchanged. It starts no exercise or restoration writes in
that case. Every stage verifies both paper contents and the workspace's other
tracked files against their starting state. It also checks the committed
Overleaf base; after each publication it verifies that the publication record
names the current Overleaf commit and published default-branch commit, before
cleanup can repair either record. On success or failure it attempts to close its
open PR, restore the Overleaf files and original tracked workspace tree with
forward commits, update the sync metadata to the restored paper,
and remove its check branch and locks (or restore the prior sync-created branch).
Commit/PR history is retained. The caller's
checkout is unchanged; fetch the restored default branch before checking again.
Restoration is attempted on both sides even if closing the PR fails. A cleanup
failure always exits nonzero and requires inspecting/recovering the scratch
pair before retrying. Loss of credentials/network, an uncatchable process kill,
or a runner deadline can prevent restoration; do not reuse the pair until
its contents, open PR and locks have been checked in that case.

The round trip defaults to 600 seconds (`--timeout <seconds>`), including waiting
for GitHub checks. Restoration reserves independent deadlines totaling at most
195 seconds: 30 for PR closure, 60 for each side's content restoration (including
the workspace sync record), 15 for branch restoration, 15 for removal of an
interrupted internal sync lock, and 15 for verification (including lock absence).
An error or timeout in one cleanup step does not skip the remaining attempts;
any such failure still exits nonzero. Lock release has at most 30 more seconds.
Lock acquisition uses the remaining
round-trip deadline. Run on a POSIX runner's main thread with enough time for
all phases; the command refuses `CI` or
`GITHUB_ACTIONS` environments. Unit tests replace Overleaf/GitHub with local Git
and fixture check results; the live command runs only where the existing token
or credential helper is already available. A remote check lock excludes another
check and makes `sync` refuse this pair until the check releases it. A killed
check's `refs/asta/overleaf-sync-lock/check-<project-id>` lock requires the same
explicit interrupted-run recovery as a killed sync; it never expires itself.
Catchable acquisition timeouts attempt bounded rollback of only their own lock
commit. Failed rollback reports recovery guidance and never permits paper sync.

Exit 0 plus `Overleaf live check PASS` means every stage and restoration passed.
Any failure exits nonzero. Output labels `pair access/setup` failures (token,
access, missing project, or an unprepared pair) separately from `release step`
failures during the exercised sync/merge/publish/conflict/restoration path.
Missing PR checks (after a 30-second discovery grace period), required reviews,
and repository rules blocking unattended merge are pair setup failures. A
completed unsuccessful check, a conflicting/outdated/unstable PR, or requested
changes fail immediately with the observed state instead of waiting for the
round-trip timeout. Pending checks and unknown merge eligibility keep polling.
If restoration also fails, the original check failure is printed alongside the
restoration failure.

Opt in on any runner with `asta workspace overleaf sync --check-repo owner/check`.
Before syncing the requested paper, the CLI looks for a pass for its own asta
version on that reserved repository. It clones the scratch repository to
validate pair isolation on every invocation. On a miss it runs the complete
check synchronously, and records a pass only after restoration succeeds. Check
failure or inability to read/write the pass record refuses paper sync. A subsequent invocation or rollback to an already passed version reuses
its pass. Use `sync --check-timeout <seconds>` to change the 600-second round-trip
limit on an uncached check. The scratch pair uses the standard `paper/` directory.

The CLI rejects the paper repository itself, including case variants and rename
redirects, as its check repository. It also rejects a scratch pair pointing at
the same Overleaf project, including supported URL suffix variants and project
ID case differences, on both cached and uncached passes. Scratch clones use the paper repository's GitHub
host and retain SSH transport when the paper's origin uses SSH. Keep the pair
exclusively reserved; do not edit it by hand or schedule normal sync against
it. Its successful PR checks and writable default branch must already be configured. No credentials are added to
CI, and an uncached live check refuses CI environments.

Pass tags use `asta-overleaf-check/<SHA-256 of asta version>` on the scratch
repository. Anyone who can create or change these tags is a trusted gate
operator. A pass attests to one released version; development builds sharing a
version share that record, so use distinct versions when validating candidates.
Do not forge pass tags or remove the gate to recover from a failure.

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
