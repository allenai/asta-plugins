#!/usr/bin/env bash
# Block until the Docker workflow's main-push run for a commit succeeds. A
# release tag only promotes images that run published and verified, so tagging
# before it passes leaves a pushed tag with no image.
set -euo pipefail

sha=${1:?usage: wait-for-main-image.sh <commit-sha>}
command -v gh >/dev/null || { echo 'gh CLI is required to check the Docker workflow' >&2; exit 1; }

for _ in $(seq 1 24); do
  runs=$(gh run list --workflow docker.yml --branch main --event push --commit "$sha" \
    --limit 20 --json databaseId,status,conclusion)
  if jq -e 'any(.[]; .conclusion == "success")' <<<"$runs" >/dev/null; then
    echo "Docker images for $sha are published and verified"
    exit 0
  fi
  active=$(jq -r '[.[] | select(.status != "completed")][0].databaseId // empty' <<<"$runs")
  if [ -n "$active" ]; then
    echo "Waiting for Docker workflow run $active on $sha"
    gh run watch "$active" --exit-status --interval 30 >/dev/null || {
      echo "Docker workflow run $active failed; fix main before tagging" >&2
      exit 1
    }
    echo "Docker images for $sha are published and verified"
    exit 0
  fi
  if jq -e 'length > 0' <<<"$runs" >/dev/null; then
    echo "The Docker workflow on $sha completed without success; rerun it or fix main before tagging" >&2
    exit 1
  fi
  sleep 5
done
echo "No main-push Docker run found for $sha; tag a commit pushed to main" >&2
exit 1
