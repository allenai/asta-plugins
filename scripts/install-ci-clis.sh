#!/usr/bin/env bash
# Install the agent CLIs locked in .github/ci-tools/package-lock.json (Dependabot
# keeps them current) and record every CLI version this run uses.
set -euo pipefail

tools=.github/ci-tools
npm ci --prefix "$tools" --no-audit --no-fund
bin="$PWD/$tools/node_modules/.bin"
claude_version="$("$bin/claude" --version)"
codex_version="$("$bin/codex" --version)"
# `npx plugins add` floats like users' installs; resolve it once so the run
# uses and names one version.
plugins_version="$(npm view plugins version)"

{
  echo "### CLI versions"
  echo "- Claude Code: $claude_version"
  echo "- Codex: $codex_version"
  echo "- plugins: $plugins_version"
} | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "$bin" >> "${GITHUB_PATH:-/dev/null}"
echo "PLUGINS_CLI=plugins@$plugins_version" >> "${GITHUB_ENV:-/dev/null}"
