# Schedule Overleaf sync

Import the project with `asta workspace overleaf pull <url>`, review the paper
and `overleaf.json` together, and merge them. Before enabling the schedule, the
project owner must **turn off Overleaf link sharing** and invite each co-author
(and the sync account) explicitly as an editor. Anyone who can edit this project
can contribute paper content to the default branch through the sync PR.

Run `asta workspace overleaf sync --project /path/to/checkout` from cron or any
scheduler. Use `--dir` for a non-default paper directory. Supply the Overleaf
Git token through `OVERLEAF_TOKEN` or the Git credential helper, configure Git's
user.name/user.email, and authenticate `gh` for the workspace repository with
contents, pull-request and issue write access. Install the GitHub CLI alongside
Asta. No runner, service account or scheduler is prescribed here.

The command uses a temporary full clone, writes only the linked paper's files
to its branch, and leaves the caller's working tree alone. A remote lock
serializes runs from different machines. It keeps one PR per project on
`asta/overleaf-sync/<project-id>`, labeled `asta:overleaf-sync`. Treat this branch
and label as reserved for sync; close an unwanted PR before restarting it.

A run with new edits updates the same PR and stops. A later run squashes that
PR only when it finds no newer Overleaf edits, the PR has no conflicts or paper
markers, and GitHub reports completed successful checks and permits merging.
No checks means wait. Failed checks or conflicts leave the PR for a person;
the PR names the workspace commit whose author should resolve a conflict.
Git authors of carried Overleaf edits receive Co-authored-by trailers in the
squash. Human resolutions on the sync branch are retained. Shared `make check`
rejects paper conflict markers before rendering, on every PR.

Publish still sends only the default branch's committed paper. New Overleaf
edits must reach that branch through the sync PR first. Publication and the two
services cannot form one transaction: an edit racing the final fetch remains
for the next run, and publish's existing ancestry and race checks apply.
Configure required checks, default-branch PR requirements and squash merging
in the repository as appropriate. The CLI publishes whatever reaches default;
it does not inspect how that content was approved.

Refusals update one persistent status on the sync PR, or one labeled issue when
no sync PR exists. Identical status is not reposted on each run. Restore access
and retry after transport failures. See [recovery](overleaf-recovery.md).

## Interrupted runs

A killed process deliberately leaves its remote lock in place. This prevents
a paused process from resuming after another publisher has taken over. Normal
errors release it automatically. If sync says a run already owns the lock,
first confirm that the owning scheduler/process has stopped; then inspect and
delete `refs/asta/overleaf-sync-lock/<project-id>` with an explicit
`git push --force-with-lease=<ref>:<observed-object-id> origin :<ref>`. Do not
remove a live run's lock. Retry sync; it reconstructs its state from GitHub and
Overleaf, including a branch pushed before PR creation. Do not expire locks
on a timer.
