# Workflow: recommended repo protections

None of these is required for the workspace to work. The defaults ship as GitHub ruleset files in the skill's `assets/rulesets/` directory, released with each version. Apply them exactly as shipped.

| Ruleset | Recommend when |
|---|---|
| `default-branch.json` — blocks force-pushes and deletion of the default branch | Every repo. |
| `docs-checks.json` — requires a PR and the `docs / build` and `docs / paper-gate` checks from GitHub Actions | A new workspace repo ([repo setup](repo-setup.md)), or the repo has a paper or co-authors and the user checks changes on a branch before updating the default branch (normally by merging a PR). Direct pushes are rejected, including admins'. No approval is required by default. |

## Apply new rulesets

1. Stop and tell the user this guide doesn't cover their repo, without applying anything, if:
   - the repo is not on github.com;
   - it already has rulesets, including inherited ones (`gh api --paginate 'repos/{owner}/{repo}/rulesets?includes_parents=true'` is not empty), or branch protection on the default branch (which also covers merge queues);
   - for `docs-checks.json`: `docs.yml` does not run on every pull request to the default branch (path filters, manual-only), or another workflow job could report `docs / build` or `docs / paper-gate`.
2. Show the user each recommended file and what it does, and ask which to apply. Under [repo setup](repo-setup.md) or Overleaf pairing, the owner's one yes covers both; don't ask for each.
3. Apply each accepted file with `gh api repos/{owner}/{repo}/rulesets -X POST --input <skill-dir>/assets/rulesets/<file>`. If GitHub refuses, give the user that command, the file and GitHub's error, and move on.
4. Read each ruleset back with `gh api repos/{owner}/{repo}/rulesets/<id>` and confirm it matches the file.

## Verify existing defaults without changing them

Overleaf pairing uses this read-only path, not **Apply new rulesets**. Its
presence does not authorize changing existing rules. Keep the github.com and
`docs.yml`/check-name preconditions above. Read all rulesets, including inherited
ones (`gh api --paginate 'repos/{owner}/{repo}/rulesets?includes_parents=true'`),
and read default-branch protection
(`gh api --include repos/{owner}/{repo}/branches/<default-branch>/protection`).
Inspect the HTTP status and JSON error body even when `gh` exits nonzero:
`200` means branch protection exists; `404` with `Branch not protected` confirms
its absence, so verification continues. For a generic `404 Not Found`, confirm
the repo, branch and credential's access to this endpoint before treating it
as absence: [GitHub also uses 404 for authentication failures](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api#404-not-found-for-an-existing-resource).
Stop if that access is inconclusive or on any other error, including a failed
ruleset listing. Never treat those failures as missing protections.

- If no rules exist, report the defaults missing. Do not apply anything as part
  of verification.
- Read each repository ruleset with `gh api repos/{owner}/{repo}/rulesets/<id>`
  and compare it with the corresponding shipped file: name, target,
  enforcement, conditions, every rule and its parameters, and no bypass
  actors. Ignore response metadata such as IDs, URLs and timestamps; compare
  unordered lists by content. Treat API-added defaults as equal only when
  their documented behavior matches the shipped file.
- Stop without changing anything if any existing ruleset differs, if there are
  duplicate, extra or inherited rulesets, or if default-branch protection is
  present. Name the difference for the owner; never overwrite it or claim the
  shipped policy is active. A missing shipped ruleset is a missing protection,
  not permission to add it. In particular, checks without a `pull_request`
  rule do not verify the sync's PR-only prerequisite.
- Confirm both shipped rulesets are active and match before reporting all repo
  protections verified or scheduling unattended sync. Report a partial match
  accurately, preserving the owner's earlier choices.

Don't recommend these by default:

- Required approvals: whether to require review is the team's call.
- Required signed commits: each contributor's machine needs signing set up first.
- Protecting `gh-pages`: the workflow pushes to it, so protection breaks deploys.
