#!/usr/bin/env bash
# Bring example-demo-pr up to the supplied release ref (default origin/main) so
# the preview the READMEs link to stays current. Merges rather than rebases,
# so no force push; the push from the releaser's credentials rebuilds the preview.
set -euo pipefail
branch=${DEMO_BRANCH:-example-demo-pr}
git check-ref-format --branch "$branch" >/dev/null
git fetch -q origin \
  '+refs/heads/main:refs/remotes/origin/main' \
  "+refs/heads/$branch:refs/remotes/origin/$branch"
ref=${1:-refs/remotes/origin/main}
target=$(git rev-parse --verify --end-of-options "$ref^{commit}")
dir=$(mktemp -d "${TMPDIR:-/tmp}/demo-pr.XXXXXX")
cleanup() {
  git worktree remove --force "$dir" >/dev/null 2>&1 || true
  rmdir "$dir" 2>/dev/null || true
}
trap cleanup EXIT
git worktree add -q --detach "$dir" "refs/remotes/origin/$branch"
if git -C "$dir" merge-base --is-ancestor "$target" HEAD; then
  # A no-op push sends no synchronize event. Refresh even an up-to-date branch
  # so a release also rebuilds a missing or previously failed preview.
  git -C "$dir" commit -q --allow-empty -m "Rebuild the example demo preview"
elif ! git -C "$dir" merge -q --no-edit -m "Merge $ref into $branch" "$target"; then
  echo "Merging $ref into $branch failed (possibly conflicts); resolve it by hand so the demo preview stays current" >&2
  exit 1
fi
git -C "$dir" push -q origin "HEAD:refs/heads/$branch"
echo "Refreshed $branch with $ref ($target); its PR preview is rebuilding"
