#!/usr/bin/env bash
set -eu

root="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
root="${root//\\//}"
root="${root%/}"

case "$root" in
  */plugins/cache/*/asta-assistant/*|*/plugins/cache/*/asta-flows/*|*/plugins/cache/*/asta-dev/*)
    tools_root="$(dirname "$(dirname "$root")")/asta-tools"
    for skills in "$tools_root"/*/skills; do
      if [ -d "$skills" ]; then exit 0; fi
    done
    ;;
  */plugins/asta-assistant|*/plugins/asta-flows|*/plugins/asta-dev)
    tools_root="$(dirname "$root")/asta-tools"
    if [ -d "$tools_root/skills" ]; then exit 0; fi
    ;;
  *)
    exit 0
    ;;
esac

message='asta-tools is required by this Asta plugin. Install it from the same Asta marketplace with /plugin install asta-tools (Claude Code) or npx plugins add allenai/asta-plugins, then start a new session.'
if [ "${1:-}" = block ]; then
  input=""
  if [ ! -t 0 ]; then input="$(cat)"; fi
  # Keep Claude Code's /plugin recovery command available when the dependency is missing.
  plugin_command='"prompt"[[:space:]]*:[[:space:]]*"/plugin([[:space:]]|")'
  if [[ "$input" =~ $plugin_command ]]; then exit 0; fi
  printf '%s\n' "$message" >&2
  exit 2
fi
printf '%s\n' "$message"
