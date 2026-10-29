# Overleaf sync setup

Setup-only steps for pairing a paper repository with an Overleaf project kept
in step by [`asta workspace overleaf sync`](overleaf-sync-command.md). Setup
checks the repo defaults the workspace already applied and asks the project
owner one yes only for what the sync alone needs; each can be turned off later,
with the consequence stated below.

## 1. What the sync can't work without

Apply these before inviting the sync account. Without them the sync fails
loudly, so they are not optional and need no per-run check.

- **Git integration for the syncing Overleaf account.** Overleaf's
  [Git integration](https://docs.overleaf.com/integrations-and-add-ons/git-integration-and-github-synchronization/git-integration)
  must be available to that account. The sync uses Git integration, not
  Overleaf's GitHub synchronization. Git integration is a
  [premium feature](https://docs.overleaf.com/getting-started/free-and-premium-plans/premium-features):
  if the project's owner has a premium plan, Git integration is available to
  every member; an account with its own plan has it on every project it can
  open. Project roles still apply: cloning and pulling require read access,
  and pushing requires Editor access. So the sync account needs its own plan
  only for projects whose owners have none. Inviting it as Editor uses one of
  the owner's collaborator slots, even if the sync account has its own plan.
  Check that the owner has a spare slot under that page's collaborator limit
  (Editors and Reviewers together). Overleaf's
  [authentication token](https://docs.overleaf.com/integrations-and-add-ons/git-integration-and-github-synchronization/git-integration/git-integration-authentication-tokens)
  page says when a Git token expires.
- **A sync identity on the repository** that can push branches and the
  `refs/asta/` refs that hold its sync record and lock, open PRs, and write
  issues for its notices.

The project owner then invites the sync account as Editor, which step 3's one
message asks for; send it before this check. Never share a personal Overleaf
token.

Check access once the sync account has accepted the invitation and made its
Git token. Copy the project's Git URL from Overleaf's Git integration dialog,
or use `https://git.overleaf.com/<project-id>` with the ID from the project's
Overleaf URL. Run `git ls-remote "https://git.overleaf.com/<project-id>"`
using the sync account's credential helper, or enter username `git` and the
token at Git's password prompt in a terminal. Never put the token in the URL
or shell command. The check must succeed before scheduling the sync.

If the check fails, first check that the invitation was accepted and that the
project ID and token are right. If a helper has cached an old credential, clear
that entry or, in a terminal, rerun
`git -c credential.helper= ls-remote "https://git.overleaf.com/<project-id>"`
to enter the current token without using or saving a cached one.
Confirm that the project owner or sync account has a plan with Git integration;
if neither does, one of them needs such a plan. A success shows read access
only: the sync also pushes, so confirm in the Share menu that the sync account
is an Editor, not a Viewer or Reviewer.

## 2. What lets it run unattended

Allow squash merges, delete branches after merge, and let the sync identity
merge: the sync squash-merges its PR to credit co-authors, and stale sync
branches don't pile up. An owner who would rather merge each sync PR can
decline; the sync then posts its notice and waits for them.

Give the workspace its checks: the sync merges its PR only after at least one
check passes. In a repository with no checks, each sync PR waits for a person
to merge it, and `main` lags Overleaf until they do.

## 3. Defaults, applied with one yes

**Check the repo's defaults; don't ask for them.** A workspace repo set up as
[repo setup](repo-setup.md) describes already has them: a private repo, a
private Pages site with PR previews, and both rulesets (`default-branch.json`,
`docs-checks.json`). Check each with `gh repo view --json visibility`,
`gh api repos/{owner}/{repo}/pages --jq .public`, and the read-back in
[repo protections](repo-protections.md). If the repo already has rules, keep
that guide's stop conditions and read-back: stop if they are not the shipped
files. Read `.asta/repo-setup.json` if present. Do not propose declined
defaults again or silently turn them on; report what is missing and its cost
from [repo setup](repo-setup.md). For a repo with a setup record, verification
does not reopen the repo-settings decision. A public or unverifiably private
site still triggers [private Pages setup](github-pages.md)'s stop condition;
do not deploy new content. For a repo that has never had that proposal, include
any missing defaults once in the message below, with their costs, and record
the choices as repo setup describes. Missing settings are not implied consent
to change them, and existing rules are never replaced.

**Ask only for what only the sync needs.** Tell the owner, in one plain message
before applying anything:

- When the repo's protections were verified, a direct push to `main` is
  refused, theirs included. Changes reach `main` through PRs whose paper
  builds. Otherwise say which protection is missing; do not schedule the
  unattended sync unless its PR-only requirement in step 5 is met.
- Co-authors keep writing in Overleaf. Their edits arrive as a sync PR that
  merges itself once it builds.
- Each default below can be turned off later in Overleaf's Share menu, with
  the consequence listed.

The same yes covers step 2's merge settings. On it, the owner does both in
Overleaf:

| Default | Without it |
|---|---|
| The sync account invited as Editor (Share → invite by email) | The sync can't push co-authors' edits back to Overleaf. |
| Link sharing off | Anyone holding an edit link can put text on `main` through the sync PR, which merges itself. |

Afterwards, confirm to the owner what is on, with a link to Settings → Rules,
and what a refused push looks like
(`GH013: Repository rule violations found`).

## 4. Told, not applied

- **Overleaf compiler and TeX Live version:** check Menu → Settings for
  pdfLaTeX and TeX Live 2026, which new projects use and the build matches.
  They aren't visible through Git.
- **Required approvals:** the team's call. The sync PR then waits for a
  reviewer, so `main` lags Overleaf.
- **Signed commits:** each contributor's machine needs signing set up first.
- **Co-author emails:** co-authors' Overleaf emails appear in the sync's commit
  credits, which a public repo makes public.
- **Watching the repo:** so the owner sees the sync's notices.

## 5. Pair and schedule

On a branch with a clean, committed paper, run
`asta workspace overleaf pull https://git.overleaf.com/<project-id>` with your
own Overleaf credential. Commit the imported paper and the `.asta/overleaf` record it
writes together, open a PR and merge it. One Overleaf project pairs with one
repository. Then schedule the sync as
[Overleaf sync](overleaf-sync-command.md) describes. A scheduled GitHub workflow
is an option only when its sync account is invited to that one project and
`main` accepts changes only through PRs.
