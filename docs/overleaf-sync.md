# Overleaf sync point

The sync uses Overleaf's Git integration, not its GitHub synchronization; see
Overleaf's "Git integration and GitHub synchronization" documentation.

## Check a release on a scratch pair

Before adopting a new CLI release, reserve a **scratch Overleaf project and its
paired scratch repository** for release checks, then run:

```sh
asta workspace overleaf check --project /path/to/scratch-checkout
```

The check assumes this model; findings that assume more are out of scope:

1. The pair is reserved for checks and nothing else writes to it, so its
   contents between checks don't matter. The check only moves the pair forward
   and restores nothing. A passing check leaves no open sync PR, no lock and no
   conflict markers on the default branch; commit/PR history accumulates.
2. A check that finds a recent check in progress (its
   `refs/asta/overleaf-sync-lock/check-<project-id>` lock) stops without
   changing anything and reports the pair as busy, not as a release failure.
   A check lock older than sync's stale-lock threshold (one hour) is from a
   check that died: the next check clears only that observed lock commit. If
   another check has replaced it, the pair is busy and nothing is changed.
   After claiming its own lock, the check closes any open sync PR and removes
   the sync branch and sync lock it left. On exit it releases only its own
   check-lock commit; a replacement owner's lock is preserved.
3. A failed check leaves its state for inspection; the next check clears it.

Current limitations: releasing the check lock is best effort. A release warning
can accompany PASS after all exercise stages passed, leaving a check lock for
the next check to reclaim once stale. This is an exception to the no-lock
postcondition, but does not skip any exercise stage. A failed lock-creation push
reports the pair busy even for access or network errors; it still exits nonzero
without recording a pass or syncing the paper.

Do not schedule normal sync against the pair, edit it by hand, or give it
collaborators. The scratch default branch's committed `.asta/overleaf/paper.json` must
match the checkout. The Git identity and existing Overleaf/GitHub authentication
are the same as for `sync`. The scratch repository must allow the check to push
to its default branch, open/close PRs, and merge through the normal sync path
after checks pass. It must have at least one successful check and no
unsatisfied review requirements. A protected paper repository is not a scratch
target.

One call writes a per-run line to `asta-release-check.tex` on Overleaf, brings
it through the sync PR and merges it, publishes a workspace edit, creates a
conflict on that file, resolves it on the sync branch, waits for that head's
checks, and merges/publishes the resolution. It calls the released `sync` and
`publish` implementation, including their normal check and merge decisions, and
polls GitHub while checks run. Each stage verifies that both sides hold the same
paper with that stage's edit and the expected Overleaf base; after each
publication it verifies the publication record.

The round trip defaults to 600 seconds (`--timeout <seconds>`), including lock
acquisition and waiting for GitHub checks. Both `--timeout` and sync's
`--check-timeout` accept 1–3540 seconds, keeping a running check and its bounded
lock release below the one-hour stale-lock threshold. Run on a POSIX runner's
main thread; the command refuses `CI` or `GITHUB_ACTIONS` environments. Unit tests
replace Overleaf/GitHub with local
Git and fixture check results.

Exit 0 plus `Overleaf live check PASS` means every stage passed. Any failure
exits nonzero. Output labels `pair busy`, `pair access/setup` failures (token,
access, missing project, or an unprepared pair) and `release step` failures
separately. Missing PR checks (after a 30-second discovery grace period),
required reviews, and repository rules blocking unattended merge are pair setup
failures. A completed unsuccessful check, a conflicting/outdated PR, or
requested changes fail immediately with the observed state. Pending checks,
unknown merge eligibility and `UNSTABLE` keep polling: GitHub reports `UNSTABLE`
while non-required checks are still running, and the pair requires none.

GitHub merge-state snapshots can fail conservatively: `BLOCKED` or `HAS_HOOKS`
is refused as soon as the rollup completes. Retry after GitHub's merge state settles. These
refusals record no pass and sync no paper; failed-check leftovers are cleared by
the next check. The standalone check also prints a generic `FAIL` line for a
busy pair; the accompanying `pair busy` diagnosis distinguishes it from a
release failure.

Opt in with `asta workspace overleaf sync --check-repo owner/check` on a runner
outside GitHub Actions. The check refuses `CI` and `GITHUB_ACTIONS` environments,
so a scheduled workflow with the gate on refuses sync whenever its asta version
has no recorded pass.
An explicitly empty or malformed `--check-repo` refuses sync; omitting the option
keeps the gate disabled.
Before syncing the requested paper, the CLI looks for a pass for its own asta
version on that reserved repository. It clones the scratch repository to
validate pair isolation on every invocation. On a miss it runs the complete
check synchronously, and records a pass only after the check passes. A busy pair, check
failure or inability to read/write the pass record refuses paper sync. A subsequent invocation or rollback to an already passed version reuses
its pass. Use `sync --check-timeout <seconds>` to change the 600-second round-trip
limit on an uncached check. The scratch pair uses the standard `paper/` directory.
If another runner records the same version's pass first, this invocation can
refuse the competing tag push; retry to reuse the recorded pass.

The CLI rejects the paper repository itself, including case variants and rename
redirects, as its check repository. It also rejects a scratch pair pointing at
the same Overleaf project, including supported URL suffix variants and project
ID case differences, on both cached and uncached passes. Scratch clones use the paper repository's GitHub
host and retain SSH transport when the paper's origin uses SSH. Keep the pair
exclusively reserved; do not edit it by hand or schedule normal sync against
it. Its successful PR checks and writable default branch must already be configured. No credentials are added to
CI, and an uncached live check refuses CI environments.

SSH transport detection recognizes `git@` and `ssh://` origins. Other scp-style
SSH usernames select HTTPS for the scratch clone and may require HTTPS
authentication; use a recognized origin form if SSH is required. Check locks
use the project-ID spelling in the committed scratch configuration, which must
remain fixed while checks are running. Supporting concurrent configuration
changes or several repositories paired to one scratch project is outside the
reserved-pair model.

Pass tags use `asta-overleaf-check/<SHA-256 of asta version>` on the scratch
repository. Anyone who can create or change these tags is a trusted gate
operator. A pass attests to one released version; development builds sharing a
version share that record, so use distinct versions when validating candidates.
Do not forge pass tags or remove the gate to recover from a failure.

`asta workspace overleaf pull` and `publish` need the last Overleaf commit whose
content the workspace already reviewed. Two records in the workspace repository
supply it; Overleaf history is never trusted to name one.

- `.asta/overleaf/paper.json` holds `url` and `base`, the Overleaf commit of the last
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
Config updates preserve unknown fields added by compatible releases, including
when the URL or base changes; unchanged configs retain their original bytes.
An additive field must remain valid when an older runner changes either the URL
or base without updating that field. If correctness requires older runners to
recompute or invalidate it (for example, a cached tree derived from `base`),
introducing the field requires a format bump.
`FORMAT_RELEASE` names the first asta release that understands that format.
An absent JSON `format` field is legacy state; an explicit `null` is malformed.
Empty PR/lock stamps and unterminated PR stamps are malformed, not legacy state.
PR/lock format numbers must contain one to nine ASCII decimal digits and be positive;
longer values are malformed regardless of Python's integer-conversion settings.
Malformed format stamps stop the sync, including publication records that would
otherwise use the damaged-record fallback. Restore the stamp from history first.
The PR format stamp follows its single managed header, allowing blank lines and
horizontal whitespace. Prose before the stamp or multiple stamps before the
record-notice section are malformed and refuse. Multiple sync header markers
are ambiguous and refuse, including literal header examples in notices;
remove those examples or restore
the header from history before retrying. Stamp examples belong only in the
record-notice section, after `<!-- asta-overleaf-record-not-used -->`, where
they do not change the PR's format.

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
that commit's `paper/` files, ignoring `.asta/overleaf/paper.json`. Files are compared by
content, because Overleaf and the workspace may use different hash functions.

The sync point is a counting record's Overleaf commit when it is in Overleaf
history and descends from `base`; otherwise it is `base`. When a record exists but
does not count, pull prints `Overleaf sync record not used: <reason>. Pull started
from the pairing record's base`, so `sync` can pass the reason on. Starting from `base`
can produce conflicts; preserving edits depends on the trusted base being correct.
If `base` itself is unreadable or not
in Overleaf history, pull starts from a counting record; with none, it refuses and
asks for `base` to be set, in a PR, to an Overleaf commit the default branch already
has. Publish proceeds only when Overleaf's head equals the sync point.

## Failure handling

Refusals are one line with a concrete action and a link to the workspace skill's
[recovery reference](../plugins/asta-tools/skills/workspace/workflows/overleaf-recovery.md).
Every remaining refusal names a fix that works.

Compatibility preflight reads the PR, live lock and publication record before
any label updates or lock acquisition. If transport or Git errors prevent
checking their formats, sync refuses without reporting on GitHub: the unreadable
state could require a newer reader. Monitor scheduled job failures and logs,
restore access and retry. Damaged records that can be read retain the documented
fallback, whose warning is emitted only when the operation uses it.

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
  advancing the record. When Overleaf still descends from `.asta/overleaf/paper.json`'s
  base and has no further collaborator edits, pull imports the published files
  matching the workspace, so its PR changes only `.asta/overleaf/paper.json`. Later
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
