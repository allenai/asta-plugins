# Overleaf sync setup

Setup-only steps for pairing a paper repository with an Overleaf project kept
in step by [`asta workspace overleaf sync`](overleaf-sync-command.md). Setup
checks the repo defaults the workspace already applied and asks the project
owner one yes only for what the sync alone needs; each can be turned off later,
with the consequence stated below.

## 1. Check repo defaults, then propose sync setup once

**Check the repo's defaults; don't ask for them.** A workspace repo set up as
[repo setup](repo-setup.md) describes already has them: a private repo, a
private Pages site with PR previews, both rulesets (`default-branch.json`,
`docs-checks.json`), and branches deleted after merge. Check each with `gh repo view --json visibility`,
`gh api repos/{owner}/{repo}/pages --jq .public`,
`gh api repos/{owner}/{repo} --jq .delete_branch_on_merge`, and
**Verify existing defaults without changing them** in
[repo protections](repo-protections.md). That read-only path accepts matching
shipped rules, and stops on different, extra or inherited rules and existing
branch protection. The guide's apply path still stops if any rules exist.
Read `.asta/repo-setup.json` if present. Do not propose declined defaults again
or silently turn them on; report what is missing and its cost
from [repo setup](repo-setup.md). For a repo with a setup record, verification
does not reopen the repo-settings decision. A public or unverifiably private
site with no explicit public-publication choice still triggers
[GitHub Pages setup](github-pages.md)'s stop condition; do not deploy new
content or change visibility as part of verification. For a repo that has
never had that proposal, include any missing defaults once in the message
below, with their costs, and record
the choices as repo setup describes. Missing settings are not implied consent
to change them, and existing rules are never replaced.

**Ask only for what only the sync needs.** Tell the owner, in one plain message
before applying anything or checking the sync account's access. Explain
step 2's prerequisites and the sync merge settings in step 3 in this same
message, including that declining unattended merging leaves PRs for the owner:

- When the repo's protections were verified, a direct push to `main` is
  refused, theirs included. Changes reach `main` through PRs whose paper
  builds. Otherwise say which protection is missing; do not schedule the
  unattended sync unless its PR-only requirement in step 5 is met.
- Co-authors keep writing in Overleaf. With unattended merging accepted,
  their edits arrive as a sync PR that merges itself once it builds.
- Each Share setting below can be changed later (remove the invite/access or
  re-enable link sharing), with the consequence listed.

On the same yes, the agent applies step 3's sync merge settings and the owner
does both in Overleaf's Share menu. These are owner actions; wait for their
completion before step 2's access check:

| Default | Without it |
|---|---|
| The sync account invited as Editor (Share → invite by email) | The sync can't push co-authors' edits back to Overleaf. |
| Link sharing off | Anyone holding an edit link can put text on `main` through the sync PR, which merges itself. |

After the checks and accepted changes, confirm what is on, with a link to
Settings → Rules. Only if the protections were verified, show what a refused
push looks like (`GH013: Repository rule violations found`); otherwise name
the missing protections and do not imply pushes are blocked.

## 2. Confirm access after the owner acts

Explain these prerequisites with step 1's proposal, before the owner invites
the sync account. Without them the sync fails loudly. After the owner accepts
and completes the Share actions, verify access once before scheduling.

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

The project owner invites the sync account as Editor under step 1's one yes.
Never share a personal Overleaf token.

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

## 3. Apply the accepted sync merge settings

Under step 1's same yes, enable squash merges (branch deletion after merge is
a repo setup default, checked in step 1):

```sh
gh repo edit <owner>/<repo> --enable-squash-merge
gh api repos/{owner}/{repo} --jq .allow_squash_merge
```

Require the read-back to be boolean `true`, and confirm the sync
identity can merge under the verified rules. If GitHub refuses or read-back
fails, give the owner the command and error; do not claim it was applied or
schedule unattended merges. Do not grant permissions to the sync identity
without the owner's separate authorization. An owner who chooses to merge
sync PRs themselves can decline this setting; the sync then posts its notice
and waits for them.

Give the workspace its checks: the sync merges its PR only after at least one
check passes. In a repository with no checks, each sync PR waits for a person
to merge it, and `main` lags Overleaf until they do. Missing checks never
justify bypassing the PR-only prerequisite in step 5.

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
