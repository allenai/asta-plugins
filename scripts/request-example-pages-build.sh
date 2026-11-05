#!/usr/bin/env bash
# Bot pushes do not trigger branch-based Pages builds. Never change the source.
set -euo pipefail
# Include the HTTP status so an unconfigured site (404) is distinguishable from
# an authentication, network or server failure. None of these may change Pages.
if response=$(gh api --include "repos/$GITHUB_REPOSITORY/pages"); then
  config=$(sed '1,/^\r*$/d' <<< "$response")
else
  case "$response" in
    HTTP/*' 404 '*) echo 'Pages is not configured; leaving it unchanged.'; exit 0 ;;
    *) echo '::error::Could not read the Pages configuration'; exit 1 ;;
  esac
fi
if ! jq -e '.build_type == "legacy" and .source.branch == "gh-pages" and .source.path == "/"' <<< "$config" >/dev/null; then
  echo 'Pages has not switched to gh-pages root; leaving its current deployment unchanged.'
  exit 0
fi
# The request's URL names /latest, not an immutable build. Do not accept the
# previous build (or another commit's build) as proof this push was published.
commit=$(gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/gh-pages" --jq .object.sha)
if [ -z "$commit" ] || [ "$commit" = null ]; then
  echo '::error::Could not identify the gh-pages commit to publish'
  exit 1
fi
build=$(gh api --method POST "repos/$GITHUB_REPOSITORY/pages/builds" --jq .url)
for ((poll=0; poll<${PAGES_POLLS:-60}; poll++)); do
  result=$(gh api "$build")
  status=$(jq -r --arg commit "$commit" 'select(.commit == $commit) | .status' <<< "$result")
  case "$status" in
    built) echo "Pages published gh-pages $commit: $build"; exit 0 ;;
    errored) echo "::error::Pages build failed for $commit: $build"; exit 1 ;;
  esac
  sleep 5
done
echo "::error::Timed out waiting for Pages to publish $commit: $build"
exit 1
