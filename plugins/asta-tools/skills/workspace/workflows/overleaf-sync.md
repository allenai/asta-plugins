# Overleaf sync setup

Setup-only steps for pairing a paper repository with an Overleaf project kept
in step by [`asta workspace overleaf sync`](overleaf-sync-command.md). Setup
checks the managed settings the workspace already applied and asks the
project owner only for what they must do in Overleaf; each setting can be
turned off later, with the consequence stated below.

## 1. Check the repo's settings, then send one message

**Check the repo's settings; don't ask for them.** A workspace repo set up as
[repo setup](repo-setup.md) describes already has them: a private or internal repo, a
private Pages site with PR previews, both rulesets (`default-branch.json`,
`docs-checks.json`), branches deleted after merge, and squash merges allowed.
Check them with
`gh repo view --json visibility`, `gh api repos/{owner}/{repo}/pages --jq .public`,
`gh api repos/{owner}/{repo}/rulesets` and
`gh api repos/{owner}/{repo} --jq '.delete_branch_on_merge, .allow_squash_merge'`,
and read `.asta/repo-setup.json` if present. Don't turn a setting the owner
turned off back on. For a repo set up without repo setup's managed settings,
add one line before the message below ("I'll also turn on Asta's managed
settings this repo lacks: …"), turn them on on the owner's reply, as repo setup
does, and record the choices. If a check fails or GitHub reports something
unexpected, say what GitHub said in one line before the message.

**Send this message, and only this, as your reply.** Before applying anything
or checking the sync account's access, send the message below, filled in, and
stop. Don't say how the repo's settings checked out; the only lines before the
message are the missing-settings line and a failed check's line above. It is
the whole reply, also when the owner asked you
to change nothing yet: no list of steps, plan, blockers, prerequisites, merge
settings or other questions, since each comes later, only if it applies. If the
request also asks to leave a setting out, add after the message what the
paragraph below the message says for it.

With a sync account:

> In your Overleaf project's Share menu, invite `<sync account>` as Editor,
> turn link sharing off and invite co-authors as Editors instead. Reply when
> that's done.

With none:

> In your Overleaf project's Share menu, turn link sharing off and invite
> co-authors as Editors instead. Reply when that's done.

Where step 5's first import needs the owner's own Overleaf Git token, add one
line: "The first import asks for your Overleaf Git token at Git's prompt; I
never see it."

The sync account is a hosted runner's Overleaf account, named by the owner's
organization. For a repo in the `allenai` organization, Ai2's is named in the
asta-dev plugin's README, section "Overleaf sync"; read it from the
asta-plugins repo,
`https://raw.githubusercontent.com/allenai/asta-plugins/main/plugins/asta-dev/README.md`,
whether or not asta-dev is installed. With none named, or when that read
fails, there is none: the paper syncs with the owner's own Overleaf Git token
when they ask (step 5).

Say more only when it applies or the owner asks: step 2's prerequisites (a
premium plan for Git integration, a collaborator slot) when the access check
fails; that a direct push to `main` is refused, theirs included, when they ask
or one is refused (`GH013`); and, if the PR-only rule is missing, that you'll
pair with `--no-schedule` so that no runner syncs it unattended.

When the owner asks about a setting, or to leave one out, send only its
"Without it" text, followed by "Turn it off anyway?" when they asked to leave
it out: a managed setting's from [repo setup](repo-setup.md#1-managed-settings)
(merging sync PRs themselves is turning squash merges off), and a Share
setting's from this table:

| Share setting | Without it |
|---|---|
| The sync account invited as Editor (Share → invite by email) | The sync can't push co-authors' edits back to Overleaf. |
| Link sharing off, each co-author invited as Editor instead | Anyone holding an edit link can put text on `main` through the sync PR, which merges itself. |

On the owner's reply, first rerun any check that failed; if it fails again,
stop and tell the owner what GitHub said, turning nothing on and pairing
nothing. Then turn on any managed setting step 1 found missing, run step 2's
access check, and pair (step 5).

## 2. Confirm access after the owner acts

Without these prerequisites the access check below fails, so explain them
when it does, or when the owner asks, never in step 1's message. After the
owner completes the Share actions, verify access once before scheduling.

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

The project owner invites the sync account as Editor, as step 1's message asks.
Never share a personal Overleaf token.

Check access once the sync account has accepted the invitation and made its
Git token. Copy the project's Git URL from Overleaf's Git integration dialog,
or use `https://git.overleaf.com/<project-id>` with the ID from the project's
Overleaf URL. Run `git ls-remote "https://git.overleaf.com/<project-id>"`
using the sync account's credential helper, or enter username `git` and the
token at Git's password prompt in a terminal. Never put the token in the URL
or shell command. The check must succeed before scheduling the sync.

Run the check only where the sync account's credential is: on the runner, or
on the owner's machine when the owner syncs with their own token. An agent
without that credential, such as a researcher's own agent pairing with a
hosted runner, skips it: the runner's first scheduled sync is the check, and
it reports a failure as a notice in the repo.

If the check fails, first check that the invitation was accepted and that the
project ID and token are right. If a helper has cached an old credential, clear
that entry or, in a terminal, rerun
`git -c credential.helper= ls-remote "https://git.overleaf.com/<project-id>"`
to enter the current token without using or saving a cached one.
Confirm that the project owner or sync account has a plan with Git integration;
if neither does, one of them needs such a plan. A success shows read access
only: the sync also pushes, so confirm in the Share menu that the sync account
is an Editor, not a Viewer or Reviewer.

## 3. How the sync merges its PRs

The sync squash-merges its own PRs, so it needs squash merges allowed, one of
repo setup's managed settings, which step 1 checks. If the owner turned them
off, the sync posts its notice and waits for them to merge each sync PR.

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
repository. The record turns on scheduled sync (`--no-schedule` keeps the paper
manual), so once the PR merges, a runner that can reach the repository syncs it
on its next run, with no request to the runner's operator. Where none does, run
the sync yourself as [Overleaf sync](overleaf-sync-command.md#schedule-sync)
describes. A scheduled GitHub workflow is an option only when its sync account
is invited to that one project and `main` accepts changes only through PRs.

Once the pairing PR merges, send only: "Your paper is paired with Overleaf:
<PR link>." With no sync account, add "Ask me to sync it after co-authors edit
it."
