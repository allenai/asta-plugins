#!/usr/bin/env bash
# Bot pushes do not trigger branch-based Pages builds. Never change the source.
set -euo pipefail
config=$(gh api "repos/$GITHUB_REPOSITORY/pages")
if ! jq -e '.build_type == "legacy" and .source.branch == "gh-pages" and .source.path == "/"' <<< "$config" >/dev/null; then
  echo 'Pages has not switched to gh-pages root; leaving its current deployment unchanged.'
  exit 0
fi
build=$(gh api --method POST "repos/$GITHUB_REPOSITORY/pages/builds" --jq .url)
for _ in {1..60}; do
  status=$(gh api "$build" --jq .status)
  case "$status" in
    built) echo "Pages published gh-pages: $build"; exit 0 ;;
    errored) echo "::error::Pages build failed: $build"; exit 1 ;;
  esac
  sleep 5
done
echo "::error::Timed out waiting for Pages: $build"
exit 1
