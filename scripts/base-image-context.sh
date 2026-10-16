#!/usr/bin/env bash
# Print a `--build-context` override that pins the Dockerfile's base image to the
# digest its publisher serves for the tag right now, pulled through mirror.gcr.io.
# CI builds use it so anonymous pull limits can't fail them; the mirror only
# affects availability, since the publisher still decides what the tag points at.
set -euo pipefail

dockerfile=${1:-Dockerfile}
ref=$(sed -n '1s/^FROM \([^ ]*\) AS asta$/\1/p' "$dockerfile")
case "$ref" in
    public.ecr.aws/docker/library/*:*) ;;
    *) echo "unsupported base image in $dockerfile: ${ref:-<none>}" >&2; exit 1 ;;
esac
name=${ref#public.ecr.aws/docker/library/}
repo=${name%%:*}
tag=${name#*:}
accept='application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'

# head_digest TOKEN_URL MANIFEST_URL
head_digest() {
    local token
    token=$(curl -fsS --retry 2 --max-time 20 "$1" | jq -er .token) || return 1
    curl -fsSI --retry 2 --max-time 20 -H "Authorization: Bearer $token" -H "Accept: $accept" "$2" \
        | tr -d '\r' | awk 'tolower($1) == "docker-content-digest:" { print $2 }' \
        | grep -E '^sha256:[0-9a-f]{64}$'
}

# Docker publishes its official images to both registries; Docker Hub doesn't
# count manifest HEAD requests against its pull limit.
if digest=$(head_digest "https://public.ecr.aws/token/?scope=repository:docker/library/$repo:pull" \
    "https://public.ecr.aws/v2/docker/library/$repo/manifests/$tag"); then
    source="public.ecr.aws/docker/library/$repo@$digest"
elif digest=$(head_digest "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/$repo:pull" \
    "https://registry-1.docker.io/v2/library/$repo/manifests/$tag"); then
    source="docker.io/library/$repo@$digest"
else
    echo "could not resolve $ref on public.ecr.aws or Docker Hub" >&2
    exit 1
fi

if curl -fsSI --retry 2 --max-time 20 -H "Accept: $accept" \
    "https://mirror.gcr.io/v2/library/$repo/manifests/$digest" >/dev/null; then
    source="mirror.gcr.io/library/$repo@$digest"
else
    echo "mirror.gcr.io lacks $repo@$digest; pulling it from $source" >&2
fi
printf '%s=docker-image://%s\n' "$ref" "$source"
