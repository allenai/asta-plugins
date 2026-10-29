# Workflow: a workspace's GitHub repo, set up with one yes

Use this when you create a workspace's GitHub repo, or set up one that exists
but is empty: the user asked to share the workspace, wants a Codespace, or
starts remotely in an empty repo. Propose everything below in one plain
message and apply it on one yes, so the owner answers once and Overleaf pairing
later checks these instead of asking again.

## 1. Propose, in one message

Say what each default does and what leaving it out costs:

| Default | Without it |
|---|---|
| A private repo | If it were public instead, anyone could read the unpublished work. |
| Its site on GitHub Pages, private, with a preview and What changed for every PR | Collaborators see the files on GitHub rather than the rendered pages, and no change can be previewed before it merges. |
| Changes reach the default branch only through PRs whose checks pass, with no force-push (`docs-checks.json`, `default-branch.json`) | A change can skip its preview and land unbuilt, and a later Overleaf sync can't merge its own PRs safely. |
| Branches deleted after their PR merges | Merged branches, including each Overleaf sync branch, pile up in the repo. |

Add that each can be turned off later in Settings (General, Pages, Rules). If
the owner wants the repo or site public, stop and ask how to proceed; never
publish publicly by default.

Record declined defaults in the workspace's `.asta/repo-setup.json`, committed
with the scaffold, for example `{"declined":["private_pages"]}`, using
`private_repo`, `private_pages`, `repo_protections` and
`delete_branch_on_merge`, and an empty list when all were accepted. Don't ask
again about a declined default; Overleaf pairing reads this record too.

## 2. Apply on one yes

Apply only what the owner accepted. When a step fails or GitHub reports
something unexpected, stop and tell the owner what GitHub said.

1. Create the repo private with a README, so the default branch exists
   (`gh repo create <owner>/<name> --private --add-readme`), or make an
   existing empty repo private. Merge that branch into the local workspace
   without losing local work or force-pushing.
2. Scaffold the Quarto build with its `docs.yml` stub manual-only, and run
   `make check`, without pushing.
3. With Pages accepted, follow [GitHub Pages setup](github-pages.md) before
   the scaffold's first push, so no content reaches a site that could be
   public. Then enable the stub's `on.push` and `on.pull_request`.
4. Push the scaffold to the default branch.
5. With protections accepted, apply both rulesets from `assets/rulesets/`
   (`gh api repos/{owner}/{repo}/rulesets -X POST --input <file>`) only now
   that `docs.yml` is on the default branch. Without Pages, apply only
   `default-branch.json`: no check would run on PRs.
6. With branch deletion accepted, run
   `gh repo edit <owner>/<name> --delete-branch-on-merge`.
7. Tell the owner what is on, with links to Settings → General, Pages and Rules.
