#!/usr/bin/env bash
# write-meta.sh — materialize a metadata JSON blob to a temp file and print
# its path, suitable for `bd update <id> --metadata @<path>` or
# `bd create ... --metadata=@<path>`.
#
# Reads JSON from stdin (or from $1 if a path is given), validates that it
# parses, and writes it under $TMPDIR with mode 0600. The path is printed on
# stdout so the caller can splice it into a bd command.
#
# Why this exists: `bd update --metadata` accepts either a JSON string or
# `@file.json`. Inlining a JSON string requires `"$(cat /tmp/x.json)"` (a
# non-bd shell op the SKILL.md frontmatter does not permit), and shell quoting
# gets fragile with embedded quotes. Materializing a file once and using
# `@path` keeps everything in `Bash(bd:*)` territory.
set -euo pipefail

tmp=$(mktemp -t research-step-meta.XXXXXX.json)
trap 'rm -f "$tmp"' ERR

if [[ $# -ge 1 ]]; then
  cp "$1" "$tmp"
else
  cat > "$tmp"
fi

if ! jq -e . "$tmp" >/dev/null 2>&1; then
  echo "write-meta: input is not valid JSON" >&2
  rm -f "$tmp"
  exit 2
fi

chmod 0600 "$tmp"
echo "$tmp"
