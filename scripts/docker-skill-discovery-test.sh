#!/usr/bin/env bash
# Smoke-test that the skills CLI can discover the plugins inside the asta image.
# Uses @latest (what users run); override SKILLS_CLI to pin in an emergency.
# Usage: docker run --rm asta:latest /opt/asta-plugins/scripts/docker-skill-discovery-test.sh
set -euo pipefail

SKILLS_CLI="${SKILLS_CLI:-skills@latest}"
npx --yes "$SKILLS_CLI" add /opt/asta-plugins --list
npx --yes "$SKILLS_CLI" add /opt/asta-plugins --list --all
