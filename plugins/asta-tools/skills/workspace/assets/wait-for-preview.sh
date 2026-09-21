#!/bin/sh
# Wait for the Pages deployment started by the current push, so a preview link
# is only reported once it is actually live.
#
#   baseline  record the Pages branch tip before pushing
#   wait      wait for the docs workflow for HEAD, then for the Pages build of
#             the commit it published
#
# A render whose output is identical leaves the Pages branch untouched and no
# Pages build ever starts, so an unchanged tip means the live preview is already
# current — waiting for a build that will never come is what reported false
# deployment failures. Transient `errored` builds are common (20 of the last
# 100, usually seconds before the successful build for the same commit), so a
# bad status is never fatal on its own — only the timeout is.
set -eu

REPO=${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}
PAGES_BRANCH=${PAGES_BRANCH:-gh-pages}
WORKFLOW=${WORKFLOW:-Build and Deploy Docs}
WORKFLOW_TIMEOUT=${WORKFLOW_TIMEOUT:-120}   # seconds to wait for the run to appear
PAGES_TIMEOUT=${PAGES_TIMEOUT:-600}         # seconds to wait for the Pages build
POLL=${POLL:-10}

state=$(git rev-parse --git-path pages-tip-before)

pages_tip() {
  gh api "repos/$REPO/commits/$PAGES_BRANCH" --jq .sha 2>/dev/null || true
}

case "${1:-wait}" in
baseline)
  tip=$(pages_tip)
  [ -n "$tip" ] || { echo "Could not read $PAGES_BRANCH on $REPO" >&2; exit 1; }
  printf '%s\n' "$tip" > "$state"
  echo "Pages baseline recorded"
  ;;
wait)
  [ -s "$state" ] || {
    echo "No baseline — run 'make preview-baseline' before pushing" >&2
    exit 1
  }
  before=$(cat "$state")
  rm -f "$state"
  branch=$(git branch --show-current)
  sha=$(git rev-parse HEAD)

  elapsed=0 run_id=
  while [ "$elapsed" -lt "$WORKFLOW_TIMEOUT" ]; do
    run_id=$(gh run list --repo "$REPO" --branch "$branch" \
      --workflow "$WORKFLOW" --limit 20 \
      --json databaseId,headSha --jq \
      "[.[] | select(.headSha==\"$sha\")][0].databaseId")
    [ -n "$run_id" ] && break
    sleep 5
    elapsed=$((elapsed + 5))
  done
  [ -n "$run_id" ] || { echo "No docs workflow run for $sha" >&2; exit 1; }
  gh run watch "$run_id" --repo "$REPO" --exit-status

  after=$(pages_tip)
  [ -n "$after" ] || { echo "Could not read $PAGES_BRANCH on $REPO" >&2; exit 1; }
  if [ "$after" = "$before" ]; then
    echo "Rendered output unchanged — the published preview is already current"
    exit 0
  fi

  elapsed=0
  while [ "$elapsed" -lt "$PAGES_TIMEOUT" ]; do
    built=$(gh api "repos/$REPO/pages/builds?per_page=10" --jq \
      "[.[] | select(.commit==\"$after\" and .status==\"built\")] | length" 2>/dev/null || echo 0)
    if [ "$built" -gt 0 ]; then
      echo "Pages published $after"
      exit 0
    fi
    sleep "$POLL"
    elapsed=$((elapsed + POLL))
  done
  echo "Pages did not publish $after within ${PAGES_TIMEOUT}s" >&2
  exit 1
  ;;
*)
  echo "usage: $0 [baseline|wait]" >&2
  exit 2
  ;;
esac
