# Overleaf sync recovery

Read this when a sync PR conflicts or `asta workspace overleaf pull` / `publish` refuses.
Each refusal is one line naming what is wrong and the fix, with a link here.
The message says whether nothing changed or an Overleaf push already succeeded.

## A commit moved `base` past Overleaf's edits

`pull` and `publish` check the newest commit that changed `paper/overleaf.json`. Every
file Overleaf changed between the old and new `base` must either hold Overleaf's new
version, be changed by that commit, or be a conflict resolved by keeping the workspace's
text (both sides had edited it). A file that still holds the old Overleaf text was skipped.

Fix: bring the named file's Overleaf edit in through a PR, or set `base` in
`paper/overleaf.json` back to the commit the message names, commit that, and run `pull`
again so the edit is merged.

## Conflict markers after `pull` (exit 3)

Resolve the markers in the sync PR. Keeping either side's text is a valid resolution.
`publish` refuses files that still contain markers.

## Workspace history is shallow

Fetch workspace history explicitly (`git fetch --unshallow origin`, or deepen the
clone enough to include the last `overleaf.json` change and its parent), then retry.
Even when the paper matches the default tip, a depth-one clone cannot prove that a
hidden base move brought in all Overleaf edits. Sync never deepens your clone itself;
a refusal leaves the paper, remote heads, branch refs and `FETCH_HEAD` unchanged.

## The sync record does not continue from its predecessor

The record's Overleaf and workspace commits must each descend from the previous
record's corresponding commit. A first record must publish directly after `base`
and attest a workspace commit descending from the last default-branch config change.
A record failing these checks is ignored with a warning. Run `pull`, resolve any
conflicts and merge the resulting paper PR before publishing again. Do not advance
`base` by hand to suppress the edits. If a record is malformed or names a non-commit
object, a workspace maintainer must restore the ref from its history, or delete that
ref to use the committed base; then pull and review before publishing.

## Origin cannot be read

Restore origin's URL, credentials, network access and advertised default branch, then
retry. An unavailable origin is a refusal: an older fallback base can reverse an
intentional workspace revert of previously published text.

## Publish waits for edits or reports an incomplete publication

When Overleaf changed, pull and merge its edits before retrying publish. If a push
succeeded but confirmation or writing the record failed, pull and merge the recovery
PR (possibly only `overleaf.json`) before publishing again. Restore reset Overleaf
history first; do not overwrite a collaborator's later edit to make confirmation pass.

## Local files, assets, or conflict markers block sync

Commit or discard uncommitted paper edits first. Reconcile independently added files,
modify/delete disagreements and concurrent asset edits in the paper PR. Resolve all
conflict markers, including choosing the workspace side where appropriate, commit the
resolution and run the workspace checks. Publish only after the paper reaches the
default branch; sync publishes whatever reaches it, so require PRs there when every
change must be reviewed.
