#!/usr/bin/env bash
# Test skill discovery in the asta Docker image.
# Usage: docker run --rm asta:latest /opt/asta-plugins/scripts/docker-skill-discovery-test.sh
set -euo pipefail

npx --yes skills@latest add /opt/asta-plugins --list
npx --yes skills@latest add /opt/asta-plugins --list --all
