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
# previous build as proof this push was published. Concurrent preview pushes
# can advance gh-pages before Pages selects its build, so descendants count too.
commit=$(gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/gh-pages" --jq .object.sha)
if [ -z "$commit" ] || [ "$commit" = null ]; then
  echo '::error::Could not identify the gh-pages commit to publish'
  exit 1
fi
build=$(gh api --method POST "repos/$GITHUB_REPOSITORY/pages/builds" --jq .url)
for ((poll=0; poll<${PAGES_POLLS:-60}; poll++)); do
  result=$(gh api "$build")
  status=$(jq -r '.status' <<< "$result")
  case "$status" in
    built|errored)
      built_commit=$(jq -r '.commit // empty' <<< "$result")
      if [ -n "$built_commit" ] && [ "$built_commit" != "$commit" ]; then
        relation=$(gh api "repos/$GITHUB_REPOSITORY/compare/$commit...$built_commit" --jq .status)
        case "$relation" in
          ahead|identical) ;;
          *) sleep 5; continue ;;
        esac
      elif [ -z "$built_commit" ]; then
        sleep 5
        continue
      fi
      if [ "$status" = built ]; then
        echo "Pages published gh-pages $built_commit (includes $commit): $build"
        exit 0
      fi
      echo "::error::Pages build failed for $built_commit (includes $commit): $build"
      exit 1
      ;;
  esac
  sleep 5
done
echo "::error::Timed out waiting for Pages to publish $commit: $build"
exit 1
