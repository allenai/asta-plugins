#!/usr/bin/env bash
set -euo pipefail

cli="$1"
reported="$2"
stable='([0-9]+\.[0-9]+\.[0-9]+)'
case "$cli" in
  claude-code) pattern="^${stable}([[:blank:]]+\\(Claude Code\\))?$" ;;
  codex) pattern="^codex-cli[[:blank:]]+${stable}$" ;;
  *) printf 'Unknown CLI: %s\n' "$cli" >&2; exit 2 ;;
esac

if [[ ! "$reported" =~ $pattern ]]; then
  printf '::error::Expected a stable %s version, got %q.\n' "$cli" "$reported" >&2
  exit 1
fi
printf '%s\n' "${BASH_REMATCH[1]}"
