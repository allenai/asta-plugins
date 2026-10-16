# Overleaf sync setup

Setup-only steps for pairing a paper repository with an Overleaf project kept
in step by [`asta workspace overleaf sync`](overleaf-sync-command.md). Setup
applies safe defaults with one yes from the project owner; each can be turned
off later, with the consequence stated below.

## 1. What the sync can't work without

Apply these before inviting the sync account. Without them the sync fails
loudly, so they are not optional and need no per-run check.

- **Git integration for the syncing Overleaf account.** Overleaf's
  [Git integration](https://www.overleaf.com/learn/how-to/Git_integration_and_GitHub_synchronization)
  must be available to that account. The sync uses Git integration, not
  Overleaf's GitHub synchronization. Git integration is a
  [premium feature](https://docs.overleaf.com/getting-started/free-and-premium-plans/premium-features):
  if the project's owner has a premium plan, every member of the project can
  clone, push and pull it; an account with its own plan can do so on every
  project it can open. So the sync account needs its own plan only for
  projects whose owners have none. That page also lists how many Editors
  each plan allows, and Overleaf's
  [authentication token](https://docs.overleaf.com/integrations-and-add-ons/git-integration-and-github-synchronization/git-integration/git-integration-authentication-tokens)
  page says when a Git token expires.
- **A sync identity on the repository** that can push branches and the
  `refs/asta/` refs that hold its sync record and lock, open PRs, and write
  issues for its notices.

Then the project owner invites the sync account as Editor (Share → invite by
email). Never share a personal Overleaf token.

Check access once the sync account has made its Git token: `git ls-remote` on
the project's Git URL (`https://git.overleaf.com/<project-id>`, username `git`,
the token as password) must succeed. If it fails, the owner upgrades to a plan
with Git integration or the sync account gets one.

## 2. What lets it run unattended

Allow squash merges and let the sync identity merge: the sync squash-merges its
PR to credit co-authors. An owner who would rather merge each sync PR can
decline; the sync then posts its notice and waits for them.

Give the workspace its checks: the sync merges its PR only after at least one
check passes. In a repository with no checks, each sync PR waits for a person
to merge it, and `main` lags Overleaf until they do.

## 3. Defaults, applied with one yes

Tell the owner, in one plain message before applying anything:

- A direct push to `main` is refused, theirs included. Changes reach `main`
  through PRs whose paper builds.
- Co-authors keep writing in Overleaf. Their edits arrive as a sync PR that
  merges itself once it builds.
- Each default below can be turned off later in Settings → Rules (Overleaf
  link sharing in Overleaf's Share menu), with the consequence listed.

On one yes, apply all of them:

| Default | Without it |
|---|---|
| No force-push on `main` (`default-branch.json`) | A force-push makes the next sync start over from its last known point, so published text can come back as conflicts, though no edit is lost. |
| Link sharing off in Overleaf | Anyone holding an edit link can put text on `main` through the sync PR, which merges itself. |
| Changes reach `main` only through PRs whose paper builds (`docs-checks.json`) | Text whose paper does not build can reach `main` and be published to Overleaf. |
| Pages previews, branches deleted after merge, and a private repo for an unpublished paper | Changes can't be previewed before merge, stale sync branches pile up, and a public repo exposes the draft. |

Apply the two rulesets as [repo protections](repo-protections.md) describes,
with its stop conditions and read-back, but both together under this one yes
rather than asking for each.

After applying, read the settings back and confirm to the owner what is on,
with a link to Settings → Rules, and what a refused push looks like
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
own Overleaf credential. Commit the imported paper and the `overleaf.json` it
writes together, open a PR and merge it. One Overleaf project pairs with one
repository. Then schedule the sync as
[Overleaf sync](overleaf-sync-command.md) describes. A scheduled GitHub workflow
is an option only when its sync account is invited to that one project and
`main` accepts changes only through PRs.
