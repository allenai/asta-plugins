# Overleaf sync

Command details for agents and schedulers. Pairing, access and repository
settings are in [setup](overleaf-sync.md); record and publication contracts in
[the technical reference](../../../../../docs/overleaf-sync.md).

## Waiting

One call pulls co-authors' Overleaf edits into a sync PR, waits for its checks
and any required approvals, merges it, then publishes the default branch's
paper back to Overleaf:

```bash
asta workspace overleaf sync --wait 1800
```

`--wait SECONDS` visits each pending paper once per round, polling every 30
seconds between rounds. It waits out the sync PR's checks, the quiet rerun
before it merges, and another run's recent lock. For a positive wait, no
further attempt starts at or after the shared deadline; an attempt already
running finishes normally so it can release its lock. `--wait 0` makes one
pass. It then prints one final `Sync outcome:` line per paper after any
progress messages and exits:

| Exit | Outcome | Next step |
|------|---------|-----------|
| 0 | complete: merged co-author edits, published | none |
| 4 | a person must act; the line names what and, for a conflict, whose change | that person acts, then rerun |
| 5 | still waiting when the deadline passed | rerun; it picks up where this run stopped |
| 1 | failed; an operator must act (credentials, permissions, a refusal) | fix the cause, rerun |

It never prompts, so an agent can start it in the background and act on the
exit code. Git runs with no terminal and your SSH command and Git config are
left as they are, so an SSH key passphrase or unknown host key fails at once
(exit 1); load the key into `ssh-agent` or use HTTPS first. With several
paired papers and no `--dir`, each paper gets its own outcome line and the exit code is the most urgent one; papers not attempted
before the deadline are reported as still waiting. Exit 4 is only for what sync
records: a conflict on the sync PR, failed or cancelled checks (the line names
each one), or a required or rejected review. Anything inferred from GitHub's
state, such as no checks yet, a draft, or a merge blocked for no stated reason,
keeps waiting; at the deadline, exit 5's line says what it last saw.

Without `--wait`, sync behaves as scheduled runners expect, described below.

## Pull and publish by hand

`sync` runs two commands an agent can also run itself. On a branch,
`asta workspace overleaf pull` brings Overleaf edits into `paper/`; once the
paper is paired, it needs no URL. Review with `git diff`, commit, and open a
PR. After that PR merges, run `asta workspace overleaf publish --dry-run`, then
`asta workspace overleaf publish`. Publish refuses if Overleaf has edits not
yet pulled, and exports only committed files: commit figures and supplied
files, since untracked ones are not published.

## Schedule sync

A paper turns on scheduled sync with `"schedule": true` in its
`.asta/overleaf/<paper dir>.json` record. `pull` sets it when it first pairs a
paper; pass `--no-schedule` to keep that paper manual. `--schedule` and
`--no-schedule` on a later `pull`, or a PR to the record, change it. A hosted
runner then runs one command on its own timer:

```bash
asta workspace overleaf sync --github-owner my-org
```

It finds that user's or org's scheduled papers with one GitHub code search,
reads each match's record to confirm, clones each repository, and pushes with
`gh`'s token. A record committed since the search index last updated is picked
up a run later. It syncs every scheduled paper and carries on past a failing
one, exiting nonzero after attempting them all. The `ghcr.io/allenai/asta`
image ships `gh`, so a hosted runner can use it as is.

On a laptop no discovery is needed: plain `sync` in the paper's checkout is the
runner, run by an agent at session start or by one cron line such as
`0 * * * * asta workspace overleaf sync --project ~/papers/my-paper`.

Plain `sync --project /path/to/checkout` visits every paper paired in that
checkout whether scheduled or not; use `--dir` to sync only one.
`pull` and `publish` require `--dir` when several papers are paired.

Supply the Overleaf Git token through `OVERLEAF_TOKEN` or a Git credential
helper (username `git`, password the token) and configure Git's identity, as
[authentication and hooks](../../../../../docs/overleaf-sync.md#authentication-and-hooks)
describes, and authenticate `gh` (for example `GH_TOKEN`) with contents,
pull-request and issue write access to each paper's repository.

The command uses a temporary full clone, writes only the linked paper's files
and its own pairing record to its branch, and leaves the caller's working tree alone. A remote
[lock](overleaf-recovery.md#interrupted-runs) serializes runs from different machines. It keeps one PR per project on
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
GitHub requires updating its base. Build-configuration changes are refused
before any sync-branch push; see [Scheduled sync needs attention](overleaf-recovery.md#scheduled-sync-needs-attention).
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
