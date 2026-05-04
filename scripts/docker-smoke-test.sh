#!/usr/bin/env bash
# Smoke-test the asta Docker image.
# Usage: docker run --rm asta:latest /opt/asta-plugins/scripts/docker-smoke-test.sh
set -euo pipefail

asta --version
asta --help >/dev/null
asta literature --help >/dev/null
asta literature find --help >/dev/null
asta auth login --help >/dev/null
asta auth print-token --help >/dev/null
quarto --version

test -d /opt/asta-plugins/skills
count=$(find /opt/asta-plugins/skills -mindepth 1 -maxdepth 1 -type d | wc -l)
test "$count" -ge 2
for d in /opt/asta-plugins/skills/*/; do
    test -f "$d/SKILL.md" || { echo "Missing SKILL.md in $d"; exit 1; }
done
test -f /opt/asta-plugins/.claude-plugin/marketplace.json

echo "All smoke tests passed"
