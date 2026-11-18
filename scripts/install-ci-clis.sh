#!/usr/bin/env bash
# Install the CLI tools locked in .github/ci-tools/package-lock.json (Dependabot
# keeps them current) and record their installed versions.
set -euo pipefail

tools=.github/ci-tools
npm ci --prefix "$tools" --no-audit --no-fund --engine-strict
bin="$PWD/$tools/node_modules/.bin"
claude_version="$("$bin/claude" --version)"
codex_version="$("$bin/codex" --version)"
plugins_version="$(node -p 'require(process.argv[1]).version' "$PWD/$tools/node_modules/plugins/package.json")"
{
  echo "### CLI versions"
  echo "- Claude Code: $claude_version"
  echo "- Codex: $codex_version"
  echo "- plugins: $plugins_version"
} | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"

if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$bin" >> "$GITHUB_PATH"
else
  echo "CLI tools installed in $bin"
fi
