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
# A previous manual refresh may already have brought in main commits beyond
# this release. Merging an older target cannot remove them; refuse to claim
# that the resulting preview represents that release. Check every common base
# so histories with multiple merge bases cannot hide an extra main ancestor.
main_bases=$(git merge-base --all refs/remotes/origin/main "refs/remotes/origin/$branch")
for base in $main_bases; do
  if ! git merge-base --is-ancestor "$base" "$target"; then
    echo "$branch already contains main commits outside $ref ($target); refusing to refresh. Wait for a release that includes them, or restore the demo branch to the intended release plus its sample edits, then retry scripts/refresh-demo-pr.sh $target" >&2
    exit 1
  fi
done
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
