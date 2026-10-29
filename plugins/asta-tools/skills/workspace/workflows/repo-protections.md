# Workflow: recommended repo protections

None of these is required for the workspace to work. The defaults ship as GitHub ruleset files in the skill's `assets/rulesets/` directory, released with each version. Apply them exactly as shipped.

| Ruleset | Recommend when |
|---|---|
| `default-branch.json` — blocks force-pushes and deletion of the default branch | Every repo. |
| `docs-checks.json` — requires the `docs / build` and `docs / paper-gate` checks from GitHub Actions | A new workspace repo ([repo setup](repo-setup.md)), or the repo has a paper or co-authors and the user checks changes on a branch before updating the default branch (normally by merging a PR). Direct pushes without passing checks are rejected, including admins'. |

1. Stop and tell the user this guide doesn't cover their repo, without applying anything, if:
   - the repo is not on github.com;
   - it already has rulesets, including inherited ones (`gh api 'repos/{owner}/{repo}/rulesets?includes_parents=true'` is not empty), or branch protection on the default branch (which also covers merge queues);
   - for `docs-checks.json`: `docs.yml` does not run on every pull request to the default branch (path filters, manual-only), or another workflow job could report `docs / build` or `docs / paper-gate`.
2. Show the user each recommended file and what it does, and ask which to apply. Under [repo setup](repo-setup.md) or Overleaf pairing, the owner's one yes covers both; don't ask for each.
3. Apply each accepted file with `gh api repos/{owner}/{repo}/rulesets -X POST --input <skill-dir>/assets/rulesets/<file>`. If GitHub refuses, give the user that command, the file and GitHub's error, and move on.
4. Read each ruleset back with `gh api repos/{owner}/{repo}/rulesets/<id>` and confirm it matches the file.

Don't recommend these by default:

- Required approvals: whether to require review is the team's call.
- Required signed commits: each contributor's machine needs signing set up first.
- Protecting `gh-pages`: the workflow pushes to it, so protection breaks deploys.
