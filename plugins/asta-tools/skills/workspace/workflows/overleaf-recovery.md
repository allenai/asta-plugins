# Overleaf sync recovery

Read this when a sync PR conflicts or `asta workspace overleaf pull` / `publish` refuses.
Each refusal is one line naming what is wrong and the fix, with a link here.
The message says whether nothing changed or an Overleaf push already succeeded.

## Record not used

`pull` printed `Overleaf sync record not used: <reason>. Pull started from
overleaf.json's base`. A record counts only when its ids are full commit ids, its
workspace commit is on the default branch, and its Overleaf commit holds that commit's
paper. A damaged record, one that does not match the default branch's history, or one
whose Overleaf commit is missing from Overleaf history is ignored. Starting from `base`
can produce conflicts in the sync PR: resolve them and merge the PR. This assumes
`base` has not been manually advanced past an unimported edit; if it has, follow
[Recovering a skipped co-author edit](#recovering-a-skipped-co-author-edit). The next `publish` writes a new record that counts.

The same fallback warning currently says `Pull started` during `publish`; it
means publish is comparing Overleaf with `base`. If Overleaf has moved beyond
that base, publish still refuses until those edits have been pulled and reviewed.

An unsupported file layout in a record's historical paper can refuse instead of
falling back. A workspace maintainer can restore a valid record from its history
or delete `refs/asta/overleaf/<project-id>` to use the committed base. Then pull
and review the result before publishing; do not change historical paper files.

For a damaged record, `publish` refuses only when the ref does not name a commit, because a
fast-forward push cannot replace it. Ask a workspace maintainer to delete the ref
(`git push origin :refs/asta/overleaf/<project-id>`) or restore it from its history,
then retry.

## Base not in Overleaf history

`base` in `paper/overleaf.json` is unreadable or not in Overleaf's history (for
example, Overleaf history was reset), and no sync record counts. Find an Overleaf
commit and set `base` to it in a PR, then review the imported changes:

1. Clone the Overleaf project: `git clone <overleaf url> /tmp/overleaf-paper`.
2. Use the root commit reachable from its current head as a conservative base:
   `git -C /tmp/overleaf-paper rev-list --max-parents=0 HEAD`.
   If it prints multiple roots, inspect that history with the collaborators before
   choosing one. Do not infer a sync point from a `Publish workspace commit`
   subject: subjects are informational and do not prove publication or review.
3. Set `base` to that full commit id, commit, open a PR and merge it. If a counting
   record would override it, have a maintainer remove that ref as described in
   [Recovering a skipped co-author edit](#recovering-a-skipped-co-author-edit).
4. Run `pull` and review the entire sync PR before merging it. A root commit is a
   recovery starting point, not proof that its contents were reviewed.

An earlier base can replay previously reviewed or reverted edits as well as cause
conflicts. Preserve intended workspace removals and resolutions during review;
do not assume a clean automatic merge is the desired paper. After a history reset,
edits absent from the current Git history must be recovered from Overleaf's History
panel or another retained clone before accepting the result.

## Recovering a skipped co-author edit

`base` is trusted as committed on the default branch. A hand edit to `base` that
moves it past an Overleaf edit, or a hand-written record, can make a pull skip a
co-author's edit. Overleaf keeps every edit. To bring one back:

1. In a clone of the Overleaf project, find the commit that made it:
   `git log -p -- <file>` (or Overleaf's History panel).
2. Set `base` in a PR to that commit's parent, or to any earlier Overleaf commit,
   and merge it.
3. If a hand-written sync record would select a later Overleaf commit, ask a
   workspace maintainer to delete `refs/asta/overleaf/<project-id>` with
   `git push origin :refs/asta/overleaf/<project-id>`. Otherwise that record can
   override the earlier base again. Keep the record deleted until the recovery
   PR has merged.
4. Run `pull`; the edit comes back in the sync PR, possibly as a conflict. Review
   and merge it before publishing; publish then writes a fresh record.

## Conflict markers after `pull` (exit 3)

Resolve the markers in the sync PR. Keeping either side's text is a valid resolution.
`publish` refuses files that still contain markers.

## Workspace history is shallow

A depth-one or shallow clone cannot show whether a record's workspace commit is on
the default branch. Fetch workspace history explicitly (`git fetch --unshallow origin`,
or deepen the clone enough to include the record's workspace commit), then retry.
Sync never deepens your clone itself; a refusal leaves the paper, remote heads, branch
refs and `FETCH_HEAD` unchanged.

## Local files, assets, or conflict markers block sync

Commit or discard uncommitted paper edits first. Reconcile independently added files,
modify/delete disagreements and concurrent asset edits in the paper PR. Resolve all
conflict markers, including choosing the workspace side where appropriate, commit the
resolution and run the workspace checks. Publish only after the paper reaches the
default branch; sync publishes whatever reaches it, so require PRs there when every
change must be reviewed.

## Sync record ref

A ref that names a tree or annotated tag cannot be replaced by a fast-forward commit
push. Ask a workspace maintainer to restore the ref to a commit from its history, or
run `git push origin :refs/asta/overleaf/<project-id>`, then retry. A damaged commit
record can be replaced by the next successful publish without deleting it.

## Incomplete publication

The Overleaf push succeeded but confirmation or recording the sync point failed.
Restore origin access if needed, run `asta workspace overleaf pull`, and merge its PR
before publishing again. That PR may change only `overleaf.json`. If Overleaf history
was reset, use [Base not in Overleaf history](#base-not-in-overleaf-history); do not
force-push over later collaborator edits.

## Project URL

Use the project's Git URL, `https://git.overleaf.com/<project-id>`, from Overleaf's
Git integration. A browser project URL or a sharing link is not a Git URL.

## Paper directory

Use a relative subdirectory of the workspace, such as `--dir paper`. To import a
different Overleaf project, choose a separate directory rather than replacing the
existing project's configuration.

## Local changes

Commit the paper changes to a branch and review them, or save a copy before discarding
them. Retry from a clean paper directory. Git index flags can hide edits from status;
compare the named file with its committed version when status looks clean.

## Ignore rules

Keep `.gitignore` in the workspace root, not inside the Overleaf paper. Adjust matching
rules so paper sources and `overleaf.json` can be committed. If checking the rules
itself failed, check local Git configuration and repository permissions, then retry.

## Local Git failure

Check the installed Git command, repository permissions and local Git configuration.
Run the failing Git operation locally for its diagnostic, repair it and retry. Sync
omits raw Git diagnostics because credential helpers and URLs can contain secrets.
If merge-file is unavailable, install a Git version that includes it or reconcile the
paper by hand and commit the result.

## Origin cannot be read

Restore origin's URL, credentials, network access and advertised default branch, then
retry. To repair the advertised branch, ask a repository maintainer to set the default
branch to an existing branch. An unavailable origin refuses before copying or pushing.

## Default branch changed

Fetch the default branch, wait for its checks to pass, and check out the new tip.
Retry with that full commit id when using `--expected-commit`. Repeated concurrent
changes require retrying after they settle, not bypassing the expected-commit guard.

## Paper configuration

For a new link, run `asta workspace overleaf pull <url>`, review the import and commit
`paper/overleaf.json`. For a damaged or modified configuration, restore its project URL
and base from Git, or set a usable base through the
[base recovery procedure](#base-not-in-overleaf-history). Commit the configuration
with the paper before publishing.

## Empty paper

Commit at least one paper source in the configured directory, or correct `--dir` to
point to the paper, then retry. Sync refuses an empty export to avoid deleting a paper.

## Git hooks and signing

Check workspace pre-push or commit hooks and signing settings. Export hooks run in the
paper-only checkout, so they must not require files outside that directory. Repair the
hook or signing setup and retry; do not bypass required hooks to publish.

## Overleaf authentication

Check `OVERLEAF_TOKEN` or the Git credential helper. Use a current token for an account
with Git access to this Overleaf project; ask its owner to restore access if needed.
Retry after access works. Do not put tokens in URLs, commits or issue comments.

## Overleaf connection

Check project access, credentials, network connectivity and the remote state. For a
rejected push, pull and review newer edits before retrying. For a hook rejection, use
[Git hooks and signing](#git-hooks-and-signing).

## Overleaf edits need review

Run `asta workspace overleaf pull`, resolve conflicts, review and merge the resulting
PR, then publish the new default-branch paper. This also repairs a lost publication
checkpoint; do not overwrite a collaborator's edits to make a push succeed.

## Empty Overleaf project

Add an initial paper file in Overleaf so its Git bridge has a commit, then retry pull.
If the project already has files, verify that its Git integration exposes a default
branch and that the supplied URL identifies the intended project.

## Initial workspace commit

Commit the workspace's initial files on a branch before linking the paper. Sync needs
a committed workspace revision to compare and preserve local changes.

## Path collision

Move the named obstructing file or directory aside, preserving a copy, then retry.
Reconcile its contents into the paper PR. Sync will not overwrite a directory with a
file or traverse a file as though it were a directory.

## Paper not on default branch

Merge the paper changes through a reviewed PR, fetch and check out the resulting
default-branch revision, then publish. Do not publish an unmerged branch. Repositories
that require review of every paper change must enforce PRs on their default branch.

## File existence conflict

One side edited a file the other deleted. Preserve both versions, decide whether the
file should exist, and reconcile that decision in the paper PR. A manual resolution
must include the corresponding Overleaf edit before advancing `base` to it.

## Independent additions

Both sides added the same path without a shared file version. Compare both additions,
keep their intended content in the paper PR and reconcile the duplicate before retrying.
Rename one addition if both should remain separate files.

## Concurrent asset edits

Save both asset versions and reconcile them with an editor that supports that format,
or choose the intended version with the collaborators. Sync cannot merge these bytes
line by line. Commit the resolved asset with the corresponding sync base in the PR.

## Git identity

Configure the workspace's Git `user.name` and `user.email` to a valid publishing
identity, then retry. These settings identify the exported Overleaf commit.

## Plain files only

Remove or rename unsafe paths, symlinks, submodules and metadata aliases, or sync those
files by hand. Convert LFS pointers to ordinary files and remove executable bits when
appropriate. Remove content-changing `.gitattributes`, Git filters or conversions
before retrying: the exported bytes must equal the committed paper bytes.
