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

Add that each can be turned off later in Settings (Pages, Rules). If the owner
declines one, apply the rest and don't ask again.

Record the decision in the workspace's `.asta/repo-setup.json`, committed with
the scaffold, so a later session can honor it. Store only the declined default
IDs, for example `{"declined":["private_pages"]}`; use `private_repo`,
`private_pages`, and `repo_protections` for the three rows, and an empty list
when all were accepted. Preserve an existing record and update it only for a
new explicit owner decision. This is a record of choices, never authorization
to change settings. Overleaf pairing reads it before proposing anything.

## 2. Apply on one yes

Apply only the defaults the owner accepted. If they decline private hosting,
do not silently enable a public site; the Pages workflow remains manual-only.
The commands below use `main`; read the repo's `default_branch` with
`gh api repos/{owner}/{repo} --jq .default_branch` and substitute it when
different, including in the scaffold's `docs.yml` push filter.

1. Create the repo private with a README, so `main` exists
   (`gh repo create <owner>/<name> --private --add-readme`), or check an
   existing one with `gh repo view <owner>/<name> --json visibility`. If an
   existing repo is public and the owner accepted the private-repo default,
   that yes covers making it private; read visibility back afterwards. A
   declined private-repo default is not permission to publish unpublished work:
   creating a public repo requires the owner's explicit choice of public.
   For an existing repo with no commits, seed `main` with an empty root commit
   (`git mktree </dev/null`, then
   `git commit-tree <empty-tree> -m 'Initialize default branch'`, then
   `git push origin <commit>:refs/heads/main`).
   Do this before creating any Pages branch, so it cannot become the default.
2. Set up the site as SKILL.md's **GitHub Pages deploy** describes, including
   its empty source branch and private-site read-back, before the scaffold's
   first push, so no rendered page deploys while the site could be public. If
   it can't be private, stop: ask the owner how to proceed and leave the
   remaining defaults unapplied until they answer.
3. Fetch the initialized default branch (`git fetch origin main`). If there
   is no local commit, start the workspace from `origin/main`, preserving any
   uncommitted files. Otherwise merge `origin/main` into the local workspace
   branch (`git merge --allow-unrelated-histories origin/main` for independent
   histories). Resolve a README conflict by preserving the workspace's content
   and useful remote text; never discard local work or force-push. Scaffold the
   Quarto build and `docs.yml` (SKILL.md, **Quarto build tool**), commit, run
   `make check`, and push `HEAD:main` as a fast-forward before any ruleset
   exists. With Pages accepted, keep `on.push` and `on.pull_request`; otherwise
   keep the manual-only stub. If `main` advances or contains more than the
   initialization commit, stop treating the repo as empty: use a PR for the
   scaffold and apply protections only after that PR lands.
4. Apply both rulesets as [repo protections](repo-protections.md) describes,
   with its stop conditions and read-back, under this one yes rather than
   asking for each. A declined site leaves the workflow manual-only, so that
   guide's `docs-checks.json` precondition is not met: report that it was not
   applied rather than installing required checks that cannot run on PRs.
5. Read the settings back and tell the owner what is on, with links to
   Settings → Pages and Settings → Rules, and what a refused push looks like
   (`GH013: Repository rule violations found`).
