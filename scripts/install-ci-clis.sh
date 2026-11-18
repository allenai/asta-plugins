#!/usr/bin/env bash
# Install the agent CLIs locked in .github/ci-tools/package-lock.json (Dependabot
# keeps them current) and record their installed versions.
set -euo pipefail

tools=.github/ci-tools
npm ci --prefix "$tools" --no-audit --no-fund --engine-strict
bin="$PWD/$tools/node_modules/.bin"
claude_version="$("$bin/claude" --version)"
codex_version="$("$bin/codex" --version)"
{
  echo "### CLI versions"
  echo "- Claude Code: $claude_version"
  echo "- Codex: $codex_version"
} | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "$bin" >> "${GITHUB_PATH:-/dev/null}"
