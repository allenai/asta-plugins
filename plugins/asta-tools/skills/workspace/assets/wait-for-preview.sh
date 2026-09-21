#!/bin/sh
# Wait for the Pages deployment started by the current push, so a preview link
# is only reported once it is actually live.
#
#   baseline  record the Pages branch tip and latest docs run before pushing
#   wait      wait for the docs workflow for HEAD, then for the Pages build of
#             the commit it published
#
# A render whose output is identical creates no deployment commit and no Pages
# build. Concurrent workflows can still move the branch, so `wait` identifies
# this workflow's deployment by its run-ID commit message instead of treating
# the branch tip as its own. Transient `errored` builds are common, so a bad
# status is never fatal on its own — only the timeout is.
set -eu

REPO=${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}
PAGES_BRANCH=${PAGES_BRANCH:-gh-pages}
WORKFLOW=${WORKFLOW:-Build and Deploy Docs}
WORKFLOW_TIMEOUT=${WORKFLOW_TIMEOUT:-120}   # seconds to wait for the run to appear
RUN_TIMEOUT=${RUN_TIMEOUT:-600}              # seconds to wait for the run to finish
PAGES_TIMEOUT=${PAGES_TIMEOUT:-600}         # seconds to wait for the Pages build
POLL=${POLL:-10}

state=$(git rev-parse --git-path preview-run-before)

positive_integer() {
  case "$2" in
    ''|*[!0-9]*|0)
      echo "$1 must be a positive integer (got '$2')" >&2
      exit 2
      ;;
  esac
}

positive_integer WORKFLOW_TIMEOUT "$WORKFLOW_TIMEOUT"
positive_integer RUN_TIMEOUT "$RUN_TIMEOUT"
positive_integer PAGES_TIMEOUT "$PAGES_TIMEOUT"
positive_integer POLL "$POLL"

pages_tip() {
  value=$(gh api "repos/$REPO/commits/$PAGES_BRANCH" --jq .sha 2>/dev/null) || value=
  printf '%s\n' "$value"
}

latest_workflow_run() {
  gh run list --repo "$REPO" --workflow "$WORKFLOW" --limit 1 \
    --json databaseId --jq '.[0].databaseId // 0' 2>/dev/null
}

case "${1:-wait}" in
baseline)
  tip=$(pages_tip)
  [ -n "$tip" ] || { echo "Could not read $PAGES_BRANCH on $REPO" >&2; exit 1; }
  run_id=$(latest_workflow_run) || {
    echo "Could not read workflow runs for '$WORKFLOW' on $REPO" >&2
    exit 1
  }
  case "$run_id" in
    ''|*[!0-9]*) echo "Invalid workflow run id: '$run_id'" >&2; exit 1 ;;
  esac
  printf '%s\n%s\n' "$tip" "$run_id" > "$state"
  echo "Preview baseline recorded"
  ;;
wait)
  [ -s "$state" ] || {
    echo "No baseline — run 'make preview-baseline' before pushing" >&2
    exit 1
  }
  before=$(sed -n '1p' "$state")
  before_run=$(sed -n '2p' "$state")
  case "$before_run" in
    ''|*[!0-9]*) echo "Invalid preview baseline — run 'make preview-baseline' again" >&2; exit 1 ;;
  esac
  branch=$(git branch --show-current)
  sha=$(git rev-parse HEAD)

  set --
  [ -z "$branch" ] || set -- --branch "$branch"
  elapsed=0 run_id=
  while [ "$elapsed" -lt "$WORKFLOW_TIMEOUT" ]; do
    if ! run_id=$(gh run list --repo "$REPO" "$@" \
      --workflow "$WORKFLOW" --limit 100 \
      --json databaseId,headSha --jq \
      "[.[] | select(.headSha==\"$sha\" and .databaseId>$before_run)][0].databaseId // empty" \
      2>/dev/null); then
      run_id=
    fi
    [ -n "$run_id" ] && break
    sleep "$POLL"
    elapsed=$((elapsed + POLL))
  done
  [ -n "$run_id" ] || {
    echo "No docs workflow run for $sha — was the baseline recorded before pushing?" >&2
    exit 1
  }

  elapsed=0 conclusion=
  while [ "$elapsed" -lt "$RUN_TIMEOUT" ]; do
    if run=$(gh run view "$run_id" --repo "$REPO" --json status,conclusion \
      --jq '[.status, .conclusion] | join(" ")' 2>/dev/null); then
      set -- $run
      if [ "${1:-}" = completed ]; then
        conclusion=${2:-}
        break
      fi
    fi
    sleep "$POLL"
    elapsed=$((elapsed + POLL))
  done
  [ -n "$conclusion" ] || {
    echo "Docs workflow $run_id did not complete within ${RUN_TIMEOUT}s" >&2
    exit 1
  }
  [ "$conclusion" = success ] || {
    echo "Docs workflow $run_id completed with conclusion '$conclusion'" >&2
    exit 1
  }

  after=$(pages_tip)
  [ -n "$after" ] || { echo "Could not read $PAGES_BRANCH on $REPO" >&2; exit 1; }
  if [ "$after" = "$before" ]; then
    rm -f "$state"
    echo "Rendered output unchanged — the published preview is already current"
    exit 0
  fi

  comparison=$(gh api "repos/$REPO/compare/$before...$after" --jq \
    "[.status, (.total_commits|tostring), (.commits|length|tostring), ([.commits[] | select(.commit.message | endswith(\" (run $run_id)\"))][-1].sha // \"\")] | join(\" \")" \
    2>/dev/null) || {
      echo "Could not correlate $WORKFLOW with $PAGES_BRANCH" >&2
      exit 1
    }
  set -- $comparison
  compare_status=${1:-}
  total_commits=${2:-}
  returned_commits=${3:-}
  published=${4:-}
  [ "$compare_status" = ahead ] || {
    echo "$PAGES_BRANCH no longer descends from the recorded baseline" >&2
    exit 1
  }
  [ "$total_commits" = "$returned_commits" ] || {
    echo "Too many concurrent $PAGES_BRANCH updates to identify this deployment safely" >&2
    exit 1
  }
  if [ -z "$published" ]; then
    rm -f "$state"
    echo "Rendered output unchanged — unrelated Pages updates were ignored"
    exit 0
  fi

  elapsed=0 pages_api_seen=0
  while [ "$elapsed" -lt "$PAGES_TIMEOUT" ]; do
    if ! built=$(gh api "repos/$REPO/pages/builds?per_page=10" --jq \
      "[.[] | select(.commit==\"$published\" and .status==\"built\")] | length" 2>/dev/null); then
      built=0
    else
      pages_api_seen=1
    fi
    if [ "$built" -gt 0 ]; then
      rm -f "$state"
      echo "Pages published $published"
      exit 0
    fi
    sleep "$POLL"
    elapsed=$((elapsed + POLL))
  done
  if [ "$pages_api_seen" -eq 0 ]; then
    echo "Could not read Pages builds for $REPO within ${PAGES_TIMEOUT}s — check Pages read access" >&2
    exit 1
  fi
  echo "Pages did not publish $published within ${PAGES_TIMEOUT}s" >&2
  exit 1
  ;;
*)
  echo "usage: $0 [baseline|wait]" >&2
  exit 2
  ;;
esac
