#!/usr/bin/env bash
set -euo pipefail

operation=${1:?expected plan, push, or promote}
tag=${2:?expected a version tag}
if ! [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "::error::Expected a final release tag in vX.Y.Z format"
  exit 1
fi
ref="refs/tags/$tag"
annotation="Created by the Release workflow"

remote_commit() {
  local refs
  refs=$(git ls-remote --tags origin "$ref" "$ref^{}") || return
  awk -v ref="$ref" '$2 == ref { tag=$1 } $2 == ref "^{}" { peeled=$1 }
    END { print (peeled != "" ? peeled : tag) }' <<<"$refs"
}

case "$operation" in
  plan)
    commit=$(remote_commit)
    if [ -z "$commit" ]; then
      echo "create_tag=true" >> "$GITHUB_OUTPUT"
    else
      # Manual tags have their own push-triggered Docker run.
      git fetch --quiet --no-tags --depth=1 origin "$ref"
      if [ "$(git cat-file -t FETCH_HEAD)" = tag ] &&
         [ "$(git cat-file tag FETCH_HEAD | sed '1,/^$/d')" = "$annotation" ]; then
        echo "tag_sha=$(git rev-parse 'FETCH_HEAD^{commit}')" >> "$GITHUB_OUTPUT"
      fi
    fi
    ;;
  push)
    expected=${3:?expected the checked main commit}
    git fetch --quiet origin main
    git merge-base --is-ancestor "$expected" origin/main
    commit=$(remote_commit)
    if [ -z "$commit" ]; then
      git -c user.name='github-actions[bot]' \
          -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
          tag --annotate --message "$annotation" "$tag" "$expected"
      # A concurrent push can win. The remote ref is never forced.
      git push origin "$ref" || echo "Tag push failed; checking the remote tag"
      commit=$(remote_commit)
    fi
    if [ "$commit" != "$expected" ]; then
      echo "::error::$tag points to ${commit:-no remote commit}; expected $expected"
      exit 1
    fi
    ;;
  promote)
    expected=${3:?expected the release commit}
    commit=$(remote_commit)
    if [ "$commit" != "$expected" ]; then
      echo "::error::$tag points to ${commit:-no remote commit}; expected $expected"
      exit 1
    fi

    echo "tag_verified=true" >> "$GITHUB_OUTPUT"
    runs=$(gh run list --repo "$GITHUB_REPOSITORY" --workflow docker.yml \
      --branch "$tag" --commit "$expected" --limit 30 --json databaseId,event,status,conclusion)
    runs=$(jq '[.[] | select(.event == "push" or .event == "workflow_dispatch")]' <<<"$runs")
    if jq -e 'any(.[]; .conclusion == "success")' <<<"$runs" >/dev/null; then
      echo "$tag's Docker release already succeeded"
      exit 0
    fi

    run=$(jq -r '[.[] | select(.status != "completed")][0].databaseId // empty' <<<"$runs")
    if [ -z "$run" ]; then
      if [ "${RETRY_FAILED_DOCKER:-false}" != true ] && jq -e 'length > 0' <<<"$runs" >/dev/null; then
        echo "$tag's Docker release previously failed. Re-run the failed Release jobs to retry promotion."
        exit 0
      fi
      run=$(gh api --method POST "repos/$GITHUB_REPOSITORY/actions/workflows/docker.yml/dispatches" \
        -H 'X-GitHub-Api-Version: 2026-03-10' -f "ref=$ref" -f "inputs[expected-sha]=$expected" |
        jq -r '.workflow_run_id | numbers')
      if ! [[ "$run" =~ ^[0-9]+$ ]]; then
        echo "::error::Docker dispatch did not return a run ID for $tag"
        exit 1
      fi
    fi
    run_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$run"
    echo "run_url=$run_url" >> "$GITHUB_OUTPUT"
    echo "Waiting for Docker release $run_url"
    timeout 170m gh run watch "$run" --repo "$GITHUB_REPOSITORY" --exit-status --interval 30
    ;;
  *)
    echo "Unknown release tag operation: $operation" >&2
    exit 2
    ;;
esac
