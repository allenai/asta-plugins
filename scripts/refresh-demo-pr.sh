#!/usr/bin/env bash
# Bring the example's demo PR (#281, branch example-demo-pr) up to origin/main so
# the preview the READMEs link to shows the release. Merges rather than rebases,
# so no force push; the push from the releaser's credentials rebuilds the preview.
set -euo pipefail
branch=${DEMO_BRANCH:-example-demo-pr}
git fetch -q origin main "$branch"
if git merge-base --is-ancestor origin/main "origin/$branch"; then
  echo "$branch already contains origin/main"
  exit 0
fi
dir=$(mktemp -d "${TMPDIR:-/tmp}/demo-pr.XXXXXX")
trap 'git worktree remove --force "$dir" >/dev/null 2>&1 || true' EXIT
git worktree add -q --detach "$dir" "origin/$branch"
if ! git -C "$dir" merge -q --no-edit -m "Merge main into $branch" origin/main; then
  echo "Merging main into $branch conflicts; resolve it by hand so the demo preview stays current" >&2
  exit 1
fi
git -C "$dir" push -q origin "HEAD:refs/heads/$branch"
echo "Updated $branch to include origin/main; its PR preview is rebuilding"
