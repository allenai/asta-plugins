# Overleaf sync recovery

Read this when a sync PR conflicts or `asta workspace overleaf pull` / `publish` refuses.
Each refusal is one line naming what is wrong and the fix; nothing is copied or pushed.

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
