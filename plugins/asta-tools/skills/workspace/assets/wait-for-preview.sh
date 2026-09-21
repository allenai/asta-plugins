#!/bin/sh
# Wait for the Pages deployment started by the current push, so a preview link
# is only reported once it is actually live.
#
#   baseline  record the newest docs workflow run before pushing
#   wait      wait for a newer run for HEAD, then for the Pages build of the
#             gh-pages commit that run published
#
# The shared workflow names each deployment commit `Deploy <event> <source-sha>`.
# That identity prevents a concurrent deployment from satisfying this wait.
# When no such commit exists, the render was unchanged and no Pages build starts.
set -eu

REPO=${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}
PAGES_BRANCH=${PAGES_BRANCH:-gh-pages}
WORKFLOW=${WORKFLOW:-Build and Deploy Docs}
WORKFLOW_TIMEOUT=${WORKFLOW_TIMEOUT:-120}   # seconds to wait for the run to appear
PAGES_TIMEOUT=${PAGES_TIMEOUT:-600}         # seconds to wait for the Pages build
POLL=${POLL:-10}

state=$(git rev-parse --git-path preview-run-before)

positive_int() {
  name=$1 value=$2
  case "$value" in ''|*[!0-9]*) value=0 ;; esac
  [ "$value" -gt 0 ] 2>/dev/null || {
    echo "$name must be a positive integer" >&2
    exit 2
  }
}

positive_int WORKFLOW_TIMEOUT "$WORKFLOW_TIMEOUT"
positive_int PAGES_TIMEOUT "$PAGES_TIMEOUT"
positive_int POLL "$POLL"

case "${1:-wait}" in
baseline)
  branch=$(git branch --show-current)
  set --
  [ -z "$branch" ] || set -- --branch "$branch"
  before=$(gh run list --repo "$REPO" "$@" --workflow "$WORKFLOW" --limit 1 \
    --json databaseId --jq '.[0].databaseId // 0')
  case "$before" in ''|*[!0-9]*)
    echo "Could not read the latest docs workflow run on $REPO" >&2
    exit 1
  esac
  printf '%s\n' "$before" > "$state"
  echo "Preview baseline recorded"
  ;;
wait)
  [ -s "$state" ] || {
    echo "No baseline — run 'make preview-baseline' before pushing" >&2
    exit 1
  }
  before=$(cat "$state")
  case "$before" in ''|*[!0-9]*)
    echo "Invalid preview baseline — run 'make preview-baseline' again" >&2
    exit 1
  esac
  branch=$(git branch --show-current)
  sha=$(git rev-parse HEAD)

  set --
  [ -z "$branch" ] || set -- --branch "$branch"
  elapsed=0 run= run_id= run_event=
  while [ "$elapsed" -lt "$WORKFLOW_TIMEOUT" ]; do
    run=$(gh run list --repo "$REPO" "$@" --workflow "$WORKFLOW" --limit 100 \
      --json databaseId,event,headSha --jq \
      "([.[] | select(.headSha==\"$sha\" and .databaseId>$before)][0] // empty) | \"\\(.databaseId) \\( .event)\"" \
      2>/dev/null || true)
    if [ -n "$run" ]; then
      run_id=${run%% *}
      run_event=${run#* }
      break
    fi
    sleep "$POLL"
    elapsed=$((elapsed + POLL))
  done
  [ -n "$run_id" ] || { echo "No docs workflow run for $sha" >&2; exit 1; }
  gh run watch "$run_id" --repo "$REPO" --exit-status

  published=$(gh api "repos/$REPO/commits?sha=$PAGES_BRANCH&per_page=100" --jq \
    "[.[] | select(.commit.message==\"Deploy $run_event $sha\")][0].sha // empty")
  if [ -z "$published" ]; then
    rm -f "$state"
    echo "Rendered output unchanged — the published preview is already current"
    exit 0
  fi

  elapsed=0
  while [ "$elapsed" -lt "$PAGES_TIMEOUT" ]; do
    built=$(gh api "repos/$REPO/pages/builds?per_page=10" --jq \
      "[.[] | select(.commit==\"$published\" and .status==\"built\")] | length" 2>/dev/null || echo 0)
    if [ "$built" -gt 0 ]; then
      rm -f "$state"
      echo "Pages published $published"
      exit 0
    fi
    sleep "$POLL"
    elapsed=$((elapsed + POLL))
  done
  echo "Pages did not publish $published within ${PAGES_TIMEOUT}s" >&2
  exit 1
  ;;
*)
  echo "usage: $0 [baseline|wait]" >&2
  exit 2
  ;;
esac
