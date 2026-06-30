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

test -f /opt/asta-plugins/.claude-plugin/marketplace.json

# Packaging check: confirm the Dockerfile's `COPY . /opt/asta-plugins` landed the
# skill tree that consumers (e.g. allenai/agent-baselines) load from — a
# .dockerignore slip would drop it silently. Its structure — per-skill SKILL.md,
# counts — is a property of the source, gated against it by the pytest suite
# (TestPluginLayout in tests/test_skills.py, tests/test_integration.py); `COPY .`
# can only omit files, not alter them, so it isn't re-derived here.
sk="/opt/asta-plugins/plugins/asta-tools/skills"
test -d "$sk" && [ -n "$(find "$sk" -mindepth 1 -maxdepth 1 -print -quit)" ] \
    || { echo "image packaging: $sk missing or empty"; exit 1; }

echo "All smoke tests passed"
