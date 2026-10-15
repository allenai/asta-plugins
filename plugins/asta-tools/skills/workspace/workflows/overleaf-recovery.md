# Overleaf sync recovery

Read this when a sync PR conflicts or `asta workspace overleaf pull` / `publish` refuses.
Each refusal is one line naming what is wrong and the fix, with a link here.
The message says whether nothing changed or an Overleaf push already succeeded.

## A commit moved `base` past Overleaf's edits

`pull` and `publish` check every base move since this project's initial import, along
first-parent workspace history. Each file Overleaf changed must hold its new version,
be changed by that move's commit, or be a conflict resolved by keeping the workspace's
text (both sides had edited it). A later valid move cannot conceal an earlier omission.

Fix: set `base` in `paper/overleaf.json` back to the Overleaf commit the message names,
commit that, and run `pull` again so the edit is merged. Merge that recovery through a
PR. The rewind cancels advances beyond the restored base; an omission before that
base still refuses, so follow the named earlier base if another refusal appears.

## Invalid or unrelated historical config

A historical config error is repaired with a new commit, never by rewriting default
branch history. Restore the last verifiable full `base` named in the refusal and the
project's valid URL, commit, then run `pull` and review its changes. A temporary
unrelated base, short ID, malformed config or invalid URL is superseded when the
config returns to that verifiable lineage. Earlier skipped edits still refuse.
Deleting and re-adding the config, or changing the URL away and back, does not reset
verification for the same project.

If Overleaf history was reset and no old base is reachable, restore that history
when possible. Otherwise preserve workspace-only edits on a separate branch, then
reimport **all** Overleaf paper files at a reachable full commit ID into a new
workspace commit. The paper in that commit must exactly match that Overleaf commit,
except for `overleaf.json`; reconcile workspace-only edits in a later reviewed commit.
Set `url` and `base` in the reimport commit. If `base` is already correct, change the
config's JSON formatting too so this explicit reimport appears in config history.
Review and merge the reimport PR before publishing. A config-only change cannot
establish this checkpoint. Existing valid base moves are still checked; reimporting
does not erase a known earlier omission.

## Conflict markers after `pull` (exit 3)

Resolve the markers in the sync PR. Keeping either side's text is a valid resolution.
`publish` refuses files that still contain markers.

## Workspace history is shallow

Fetch workspace history explicitly (`git fetch --unshallow origin`, or deepen the
clone enough to include first-parent `overleaf.json` history back to this project's
initial import, each change's parent, and publication sources since the current base),
then retry. Record verification stops at the committed base; checking earlier base
moves still needs the config history so a later pull cannot hide a skipped edit.
Even when the paper matches the default tip, a depth-one clone cannot prove that a
hidden base move brought in all Overleaf edits. Sync never deepens your clone itself;
a refusal leaves the paper, remote heads, branch refs and `FETCH_HEAD` unchanged.

## The sync record does not continue from its predecessor

The record's workspace commit must descend from the previous record's workspace
commit. Its Overleaf commit must have exactly one parent equal to the previous sync
point (the preceding record, or a newer committed pull's base). Merges and gaps in
that publication chain are rejected. A first record must have exactly one parent,
`base`, and attest a workspace commit descending from the last default-branch config
change.
Pull ignores a record failing these checks with a warning. Run `pull`, resolve any
conflicts and merge the resulting paper PR. Publish refuses to append to that rejected
chain, even after the pull: ask a workspace maintainer to restore the ref from its
history or delete it, then pull and review any remaining edits before publishing.
Do not advance `base` by hand to suppress edits. Malformed JSON, invalid commit IDs,
a different project URL or a missing predecessor also refuse before copying or pushing;
a malformed predecessor is never treated as a first record.

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
