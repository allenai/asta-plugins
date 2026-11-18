# Workflow: a workspace's GitHub repo, with Asta's managed settings

Use this when you create a workspace's GitHub repo, or set up one that exists
but is empty: the user asked to share the workspace, wants a Codespace, or
starts remotely in an empty repo. The request is the owner's yes: apply the
managed settings below without asking about them or explaining them, so the
owner answers nothing before seeing the site, and Overleaf pairing later checks
these instead of asking.

## 1. Managed settings

Apply every setting in this table that the owner hasn't turned off:

| Setting | Without it |
|---|---|
| A private repo | Anyone could read the unpublished work. |
| Its site on GitHub Pages, private, with a preview and What changed for every PR | Collaborators see the files on GitHub rather than the rendered pages, and no change can be previewed before it merges. |
| Changes reach the default branch only through PRs whose checks pass, with no force-push (`docs-checks.json`, `default-branch.json`) | A change can skip its preview and land unbuilt, and a later Overleaf sync can't merge its own PRs safely. |
| Branches deleted after their PR merges | Merged branches, including each Overleaf sync branch, pile up in the repo. |
| Squash merges allowed (GitHub's default), which Overleaf sync uses to merge its own PRs | Each Overleaf sync PR waits for you to merge it, and `main` lags Overleaf until you do. |

Don't list or explain them up front. When the owner asks to leave a setting
out, in the request or later, send only that setting's "Without it" text, as
written above, followed by "Turn it off anyway?", and stop. On their yes, leave
it out (or turn it off) and record it. When the owner asks about a setting,
answer with the same text.

If the owner wants the repo or site public, stop and ask how to proceed; never
publish publicly by default.

Record settings the owner turned off in the workspace's `.asta/repo-setup.json`,
committed with the scaffold, for example `{"declined":["private_pages"]}`, using
`private_repo`, `private_pages`, `repo_protections`, `delete_branch_on_merge`
and `squash_merge`, and an empty list when all are on. Don't apply a
turned-off setting again; Overleaf pairing reads this record too.

## 2. Apply

Apply each setting that is on. When a step fails or GitHub reports something
unexpected, stop and tell the owner what GitHub said. Delegated setup handles
permission failures in its own handoff.

Before step 1, check that `gh api user -q .login` is the requester (the person
who asked for the workspace). If it isn't, or you can't tell, follow
[repo setup for someone else](repo-setup-delegated.md) before creating the repo
or pushing anything.

1. Create the repo private with a README, so the default branch exists
   (`gh repo create <owner>/<name> --private --add-readme`), or make an
   existing empty repo private. If it has no branches, push an empty-tree root
   commit to `main` first, before any Pages branch. Merge the established default
   branch into the local workspace without losing local work or force-pushing.
2. Scaffold the Quarto build with its `docs.yml` stub manual-only, and run
   `make check`, without pushing.
3. With Pages on, follow [GitHub Pages setup](github-pages.md) before
   the scaffold's first push, so no content reaches a site that could be
   public. Then enable the stub's `on.push` and `on.pull_request`.
4. Push the scaffold to a branch and open a PR, so that the owner sees the
   site's preview before it's published and GitHub signs the squash merge (no
   signing prompt on their machine stalls the setup). Wait for the PR checks
   with Pages on. Without Pages there is no preview or PR check, so use the
   passing `make check` from step 2.
   - For delegated setup without confirmed admin access, use the
     [delegated handoff](repo-setup-delegated.md#5-return-to-repo-setup).
   - Otherwise, with Pages on, send only: "Your workspace is ready for a
     look: <preview link>. Merge <PR link> to publish it, and tell me; I'll
     then finish the setup." With a paper, add "Its paper's PDF: <PDF link>."
   - Otherwise, with Pages off, send only: "Merge <PR link> to add the
     workspace, and tell me." In step 7 link the repo in place of the site.

   The requester or an authorized maintainer merges the PR. Merge it yourself
   only if the requester explicitly asks you to and your policies allow it.
   Continue at step 5 after the PR merges.
5. With protections on, apply both rulesets from `assets/rulesets/`
   (`gh api repos/{owner}/{repo}/rulesets -X POST --input <file>`) only now
   that `docs.yml` is on the default branch. Without Pages, apply only
   `default-branch.json`: no check would run on PRs.
6. Run `gh repo edit <owner>/<name>` with `--delete-branch-on-merge` and
   `--enable-squash-merge`, each only if its setting is on.
7. Send only this, filled in, as your whole reply: "Your workspace is set up:
   <site link>. It uses Asta's managed settings, shown in <Settings link>."
   For delegated setup, use the read-only
   [access check](repo-setup-delegated.md#read-access-and-choose-one-line) and
   add its access line.
   If they asked for Overleaf, add "Next, Overleaf: send me your
   Overleaf project's link." No list of what was turned on, and no notes on
   how you did it. If a setting isn't on, say instead in one line which
   and what GitHub said.
