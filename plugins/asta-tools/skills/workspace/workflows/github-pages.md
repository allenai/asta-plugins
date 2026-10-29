# Workflow: private GitHub Pages setup

Run this before pushing or enabling the docs deployment workflow. A private
repository does not by itself make its Pages site private. Keep the source
empty until the API confirms the site's `public` field is exactly `false`.
See GitHub's [Pages API](https://docs.github.com/en/enterprise-cloud@latest/rest/pages/pages)
and [publishing-source requirements](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## 1. Inspect before changing anything

Read `gh api repos/{owner}/{repo}/pages`. Only a confirmed missing site takes
the creation path below; other read failures stop setup. If Pages exists with
a source other than `gh-pages` at `/`, stop and tell the owner rather than
replacing their configuration. For an existing site on that source, set
`public=false` and verify it as in step 3 before any new deployment; do not
recreate it or overwrite `gh-pages`.

## 2. Create a new site from an empty branch

Ensure the remote default branch exists first ([repo setup](repo-setup.md)).
Choose an unused branch name such as `asta-pages-setup-<unique-suffix>` and
check that `git ls-remote --heads origin <branch>` succeeds with no matching
ref. Create a root commit with an empty tree, without switching branches or
copying anything from the workspace. With `pages_setup_branch` set to that
unused name:

```sh
pages_setup_tree=$(git mktree </dev/null)
pages_setup_commit=$(printf '%s\n' 'Initialize empty Pages source' | git commit-tree "$pages_setup_tree")
git push origin "$pages_setup_commit:refs/heads/$pages_setup_branch"
```

Require each command to succeed. Confirm the remote branch points at that
commit and `git ls-tree -r "$pages_setup_commit"` is empty. Keep it empty:
no workflow may write to it. Create Pages on this branch, never on an existing
`gh-pages` branch that could already contain unpublished work:

```sh
gh api repos/{owner}/{repo}/pages -X POST -f build_type=legacy \
  -f "source[branch]=$pages_setup_branch" -f 'source[path]=/'
```

## 3. Make the site private and verify it

Run `gh api repos/{owner}/{repo}/pages -X PUT -F public=false`, then read
`gh api repos/{owner}/{repo}/pages` and require `public` to be the boolean
`false`. An API refusal, a failed read, or any other value stops setup. If
you just created the site, delete it with
`gh api repos/{owner}/{repo}/pages -X DELETE` and confirm it is gone before
removing the empty setup branch. Report any cleanup failure. Tell the owner
privacy could not be confirmed, include GitHub's error, and ask how to
proceed. Do not enable deployment or substitute public hosting.

## 4. Attach the real source only after privacy is confirmed

Check `git ls-remote --heads origin gh-pages`. If it is missing, create it
from the same empty commit with
`git push origin "$pages_setup_commit:refs/heads/gh-pages"`; preserve it if
it already exists. Then configure the site with
`gh api repos/{owner}/{repo}/pages -X PUT --input <skill-dir>/assets/github-pages.json`.
Read it back and require `public: false`, `build_type: legacy`, and source
`gh-pages` at `/`. If the update or read-back fails, stop as in step 3; do
not proceed to a content deployment. Once verified, delete only the empty
setup branch you created. Return the site's actual `html_url` from the API;
do not guess a private site's hostname.
