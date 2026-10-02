#!/usr/bin/env bash
set -eu

root="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
root="${root%/}"

if [ -n "$root" ]; then
  parent="$(dirname "$root")"
  case "$root" in
    */plugins/cache/*)
      marketplace="$(dirname "$parent")"
      for skills in "$marketplace"/asta-tools/*/skills; do
        if [ -d "$skills/workspace" ]; then exit 0; fi
      done
      ;;
    *)
      if [ -d "$parent/asta-tools/skills/workspace" ]; then exit 0; fi
      ;;
  esac
fi

message='asta-tools is required by this Asta plugin. Install it with /plugin install asta-tools@asta-plugins (Claude Code) or npx plugins add allenai/asta-plugins, then start a new session.'
if [ "${1:-}" = block ]; then
  printf '%s\n' "$message" >&2
  exit 2
fi
printf '%s\n' "$message"
