#!/usr/bin/env bash
set -euo pipefail

version="$(<.github/codex-version)"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo '::error::Expected a numeric major.minor.patch version in .github/codex-version.' >&2
  exit 1
fi

npm install -g "@openai/codex@$version"
installed="$(codex --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
if [[ "$installed" != "$version" ]]; then
  printf '::error::Requested Codex %s, but the installed version is %s.\n' "$version" "$installed" >&2
  exit 1
fi
