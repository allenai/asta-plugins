# Overleaf sync

This is the agent and scheduler command reference. For when to sync and the
short manual workflow, read [the researcher guide](../assets/DEVELOPER.md#sync-a-paper-with-overleaf).
Pairing, access and repository settings belong in [setup](overleaf-sync.md).
Record and publication contracts belong in [the technical reference](../../../../../docs/overleaf-sync.md).

## Sync by hand

```bash
asta workspace overleaf sync --wait 1800
```

`--wait SECONDS` visits each pending paper once per round, polling every 30
seconds between rounds, until it completes or someone must act. For a positive
wait, no further attempt starts at or after the shared deadline; an attempt
already running finishes normally so it can release its lock. `--wait 0` makes
one pass over all paired papers without polling. It waits out the sync PR's
checks, the quiet rerun before it merges, and another run's recent lock, then
prints one final `Sync outcome:` line per paper after any progress messages and exits:

| Exit | Outcome | Next step |
|------|---------|-----------|
| 0 | complete: merged co-author edits, published | none |
| 4 | a person must act; the line names what and, for a conflict, whose change | that person acts, then rerun |
| 5 | still waiting when the deadline passed | rerun; it picks up where this run stopped |
| 1 | failed; an operator must act (credentials, permissions, a refusal) | fix the cause, rerun |

It never prompts, so an agent can start it in the background and act on the
exit code. Git runs with no terminal and your SSH command and Git config are
left as they are, so an SSH key passphrase or unknown host key fails at once
(exit 1) instead of waiting; load the key into `ssh-agent` or use HTTPS first. A rerun reconstructs its state from GitHub and Overleaf, so stopping
or timing out loses nothing. With several paired papers and no `--dir`, each
paper gets its own outcome line and the exit code is the most urgent one.
Papers not attempted before the shared deadline are reported as still waiting.
Exit 4 is only for what sync records: a conflict on the sync PR, failed or
cancelled checks (the line names each one), or a required or rejected review. Anything inferred from GitHub's state,
such as no checks yet, a draft, or a merge blocked for no stated reason, keeps
waiting; at the deadline, exit 5's line says what it last saw.

Without `--wait`, sync behaves as scheduled runners expect, described below.

## Schedule sync

Run `asta workspace overleaf sync --project /path/to/checkout` from cron or any
scheduler. Without `--dir`, it visits every paper paired by a tracked
`.asta/overleaf/<paper dir>.json` record, including nested paper directories.
Use `--dir` to sync only one pairing. A failure on one paper does not stop the
remaining papers; the command reports each failure and exits nonzero after
attempting them all. `pull` and `publish` require `--dir` when several papers
are paired. Configure [Overleaf authentication and Git identity](../../../../../docs/overleaf-sync.md#authentication-and-hooks),
and authenticate `gh` for the workspace repository with contents, pull-request
and issue write access. Install the GitHub CLI alongside Asta. No runner,
service account or scheduler is prescribed here.

The command uses a temporary full clone, writes only the linked paper's files
and its own pairing record to its branch, and leaves the caller's working tree alone. A remote lock
serializes runs from different machines. It keeps one PR per project on
`asta/overleaf-sync/<project-id>`, labeled `asta:overleaf-sync`. Treat this branch
and label as reserved for sync; close an unwanted PR before restarting it.
Without an open sync PR, the command replaces that branch only when it holds
sync-created paper commits; otherwise it refuses until you move the branch aside.
Fork PRs with the same branch name are ignored. Ownership is checked using the
exact sync commit subjects and the diff limited to the paper and its pairing
record, not cryptographic attestation.
People with repository push access are trusted, as with pull/publish; they can
copy these subjects. The build-configuration guard described below is not a
general execution sandbox. Quarto metadata, notebooks and filters can also execute code. Trust invited editors with the imported build
inputs before enabling automatic previews, keep TeX shell escape disabled, and
run paper builds without privileged tokens or secrets.

A run with new edits updates the same PR and stops. A later run squashes that
PR only when it finds no newer Overleaf edits, the PR has no conflicts or paper
markers, and GitHub reports completed successful checks and permits merging.
With no checks configured, the PR waits for a person to merge it. An empty
checks list is reported as checks not yet visible because CI may still start.
Failed checks or conflicts leave the PR for a person.

Sync exits 0 when the run ends waiting on people: a conflict recorded on the
sync PR, or a PR waiting for checks or a reviewer. It exits nonzero only when
an operator must act, such as an authentication or permission failure, a
refusal, or a conflict it could not record on GitHub, so a scheduler's failure
alert means someone has to step in.
The PR description normally says only that it holds co-author edits and merges
itself; it does not restate what GitHub's merge box shows. A conflict adds one
line, removed once resolved, that links each conflicting workspace change and
@-mentions its GitHub author, says fixes pushed to the sync branch are kept, and
links the conflict recovery section by full URL.
Git authors of carried Overleaf edits receive Co-authored-by trailers in the
squash. These include their Overleaf account email addresses in Git history,
which becomes public if the workspace repository is public or later published.
Confirm that this is appropriate for the project before enabling sync.
Human resolutions on the sync branch are retained. Shared `make check`
rejects conflict markers in known text paper sources before rendering, on every
PR. Standalone `=======` lines in Markdown or plain text are allowed as headings
or separators; opening and closing conflict labels are still refused.

Unrelated default-branch changes do not restart the sync PR's checks, unless
GitHub requires updating its base. Changes to `latexmkrc` or `.latexmkrc`
(including nested files, additions and deletions) refuse before any sync-branch
push and are reported on the labeled issue, even if a sync PR exists. A person
must review and import them manually. These files execute build commands;
refusing only at merge would allow CI to execute them before review.
The quiet-run merge guard queries the remote default tip immediately before
merging. While waiting, the command prints GitHub's merge state and the required
action; the PR description stays unchanged.

Publish still sends only the default branch's committed paper. New Overleaf
edits must reach that branch through the sync PR first. An edit racing the
final fetch remains for the next run; publication's
[ancestry and race checks](../../../../../docs/overleaf-sync.md#failure-handling) apply.
For required checks, PRs, approvals and squash merging, follow [setup](overleaf-sync.md).

Refusals update one persistent status on the sync PR, or one labeled issue when
no sync PR exists (including publication failures after a sync PR has merged).
Identical status is not reposted on each run. A successful PR update clears its
old refusal text. If labeling a new PR fails, the next run repairs the label after verifying the sync marker, base and current branch head.
When pull starts from the committed `base` because a record cannot be used,
the PR retains the one-line reason and a full URL to the recovery guidance.
The same line is posted in one labeled repository issue per project; reruns
reuse that record even after the issue is closed. A later run whose record
counts again closes that issue, so a future fallback posts a new one.
Restore access and retry after transport failures. See [recovery](overleaf-recovery.md).

## Interrupted runs

An interrupted process can leave its remote lock in place. Age never transfers
ownership. See [lock recovery](overleaf-recovery.md#interrupted-runs) before
removing one; never expire locks on a timer.
