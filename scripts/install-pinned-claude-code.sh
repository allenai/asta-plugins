#!/usr/bin/env bash
set -euo pipefail

version="$(<.github/claude-code-version)"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo '::error::Expected a numeric major.minor.patch version in .github/claude-code-version.' >&2
  exit 1
fi

curl -fsSL https://claude.ai/install.sh | bash -s "$version"
reported="$("$HOME/.local/bin/claude" --version)"
installed="$(bash scripts/parse-cli-version.sh claude-code "$reported")"
if [[ "$installed" != "$version" ]]; then
  printf '::error::Requested Claude Code %s, but the installed version is %s.\n' "$version" "$installed" >&2
  exit 1
fi
echo "$HOME/.local/bin" >> "$GITHUB_PATH"
