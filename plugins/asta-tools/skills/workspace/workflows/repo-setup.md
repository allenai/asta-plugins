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

## 2. Apply on one yes

1. Create the repo private with a README, so `main` exists
   (`gh repo create <owner>/<name> --private --add-readme`), or check an
   existing one with `gh repo view <owner>/<name> --json visibility`. If an
   existing repo is public, ask the owner before changing its visibility.
2. Set up the site as SKILL.md's **GitHub Pages deploy** describes, including
   making it private and checking that it is, before the scaffold's first push,
   so no rendered page deploys while the site could be public. If it can't be
   private, stop: ask the owner how to proceed and leave the remaining defaults
   unapplied until they answer.
3. Scaffold the Quarto build and the `docs.yml` workflow with `on.push` and
   `on.pull_request` (SKILL.md, **Quarto build tool**), commit, and push it to
   the default branch before any ruleset exists.
4. Apply both rulesets as [repo protections](repo-protections.md) describes,
   with its stop conditions and read-back, under this one yes rather than
   asking for each.
5. Read the settings back and tell the owner what is on, with links to
   Settings → Pages and Settings → Rules, and what a refused push looks like
   (`GH013: Repository rule violations found`).
