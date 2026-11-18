#!/usr/bin/env bash
set -euo pipefail

version="$(<.github/codex-version)"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo '::error::Expected a numeric major.minor.patch version in .github/codex-version.' >&2
  exit 1
fi

npm install -g "@openai/codex@$version"
codex_bin="$(npm prefix -g)/bin"
reported="$("$codex_bin/codex" --version)"
installed="$(bash scripts/parse-cli-version.sh codex "$reported")"
if [[ "$installed" != "$version" ]]; then
  printf '::error::Requested Codex %s, but the installed version is %s.\n' "$version" "$installed" >&2
  exit 1
fi

printf '%s\n' "$codex_bin" >> "$GITHUB_PATH"
