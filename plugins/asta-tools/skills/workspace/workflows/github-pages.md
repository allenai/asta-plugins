# Workflow: GitHub Pages setup

Run this before pushing or enabling the docs deployment workflow. A private
repository does not make its Pages site private, so make the site private and
read it back before any content reaches it. If GitHub refuses, or reports
anything unexpected, stop and tell the owner what GitHub said; never fall back
to a public site.

1. Read `gh api repos/{owner}/{repo}/pages`. If a site exists, don't replace
   it: check that it is private (step 3) before deploying to it.
2. Otherwise create the site from an empty branch, so there is nothing to
   publish yet: push a root commit with an empty tree
   (`git commit-tree $(git mktree </dev/null) -m 'Empty Pages source'`) to a
   new branch such as `asta-pages-setup`, then
   `gh api repos/{owner}/{repo}/pages -X POST -f build_type=legacy -f 'source[branch]=asta-pages-setup' -f 'source[path]=/'`.
3. Run `gh api repos/{owner}/{repo}/pages -X PUT -F public=false`, then read
   the site back and require `public` to be `false`.
4. Only then point it at `gh-pages` (create it from the same empty commit if
   missing) with
   `gh api repos/{owner}/{repo}/pages -X PUT --input <skill-dir>/assets/github-pages.json`,
   delete the setup branch, and report the site's `html_url` from the API.
