# Workflow: GitHub Pages setup

Run this before pushing or enabling the docs deployment workflow. A private
repository does not by itself make its Pages site private. New workspace sites
default to private, including a new site in a public repo. Keep the source
empty until the API confirms the site's `public` field is exactly `false`.
See GitHub's [Pages API](https://docs.github.com/en/enterprise-cloud@latest/rest/pages/pages)
and [publishing-source requirements](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## 1. Inspect and agree on visibility

Read `gh api repos/{owner}/{repo}/pages`. Only a confirmed missing site takes
the creation path below; other read failures stop setup. If Pages exists with
a build type other than `legacy` or a source other than `gh-pages` at `/`,
stop and tell the owner rather than replacing their configuration. Record an
existing site's visibility and source before changes. Under repo setup, the
accepted private-site default authorizes making it private. Outside that flow,
ask before changing visibility. For an existing public site, explain the
exposure and ask whether to keep it public or make it private before deploying
new content. An already-private site needs only the read-back, not a visibility
change. Never recreate an existing site or overwrite its `gh-pages` branch.

Only an owner's explicit choice to publish publicly permits a public site.
Explain that anyone could read the rendered unpublished work, and that a
public repo also exposes its source. A request for a deployed URL alone is not
that choice. For an explicit public choice, follow the same empty-source
sequence and read-backs below with boolean `true` instead of `false`. Public
hosting is never an automatic fallback when private hosting fails: stop for
the owner's decision first. A recorded decline of Pages does not choose public
hosting.

## 2. Create a new site from an empty branch

For an existing site, skip creation and continue at step 3. Otherwise ensure
the remote default branch exists first ([repo setup](repo-setup.md)). Choose
an unused branch name such as `asta-pages-setup-<unique-suffix>` and check that
`git ls-remote --heads origin <branch>` succeeds with no matching ref. Create
a root commit with an empty tree, without switching branches or copying
anything from the workspace. With `pages_setup_branch` set to that unused name:

```sh
git var GIT_AUTHOR_IDENT >/dev/null
git var GIT_COMMITTER_IDENT >/dev/null
pages_setup_tree=$(git mktree </dev/null)
pages_setup_commit=$(printf '%s\n' 'Initialize empty Pages source' | git commit-tree "$pages_setup_tree")
git push origin "$pages_setup_commit:refs/heads/$pages_setup_branch"
```

Require each command to succeed. If identity is missing, configure the known
contributor identity before continuing, never guess an owner's name or email.
Confirm the remote branch points at that commit and
`git ls-tree -r "$pages_setup_commit"` is empty. Keep it empty: no workflow may
write to it. Create Pages on this branch, never on an existing `gh-pages`
branch that could already contain unpublished work:

```sh
gh api repos/{owner}/{repo}/pages -X POST -f build_type=legacy \
  -f "source[branch]=$pages_setup_branch" -f 'source[path]=/'
```

## 3. Make the site private and verify it

Run `gh api repos/{owner}/{repo}/pages -X PUT -F public=false` (skip the PUT
for an existing, already-private site), then read
`gh api repos/{owner}/{repo}/pages` and require `public` to be the boolean
`false`. An API refusal, a failed read, or any other value stops setup and
uses the failure cleanup below. Tell the owner privacy could not be
confirmed, include GitHub's error, and ask how to proceed. Do not enable
deployment or substitute public hosting.

## 4. Attach the real source only after privacy is confirmed

Check `git ls-remote --heads origin gh-pages` and require the lookup to
succeed. If it is missing, create an empty root commit as in step 2 if this
run has none, then create the branch with
`git push origin "$pages_setup_commit:refs/heads/gh-pages"`; preserve it if
it already exists. Configure the site with
`gh api repos/{owner}/{repo}/pages -X PUT --input <skill-dir>/assets/github-pages.json`.
Read it back and require `public: false`, `build_type: legacy`, and source
`gh-pages` at `/`. If the update or read-back fails, use the failure cleanup;
do not proceed to a content deployment. Once verified, delete only the empty
setup branch you created, using the lease below. Return the site's actual
`html_url` from the API; do not guess a private site's hostname.

## Failure cleanup (any step)

Track which site and branches this run created. If the creation POST's result
is uncertain, inspect it before retrying or deleting anything; if ownership
cannot be established, preserve it and report the uncertainty. If this run
created the site, delete it with
`gh api repos/{owner}/{repo}/pages -X DELETE` and require a confirmed missing
site on read-back before deleting its empty branches. Never delete a site
that existed before this run. For an existing site's failed source update,
restore its recorded source if it changed; keep any successfully established
private visibility rather than restoring a public one.

Delete only this run's setup branch and newly created `gh-pages`, only when
they are no longer an active Pages source and still point at the recorded
empty commit. Use a deletion lease on that exact commit
(`git push --force-with-lease=refs/heads/<branch>:<empty-commit> origin :refs/heads/<branch>`)
so another contributor's new content cannot be deleted. Preserve all
pre-existing branches. If deletion or source restoration fails, preserve the
branches and report the exact cleanup still needed. Never deploy content
after a failed privacy check.
