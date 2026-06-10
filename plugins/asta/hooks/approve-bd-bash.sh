#!/bin/bash
# Auto-approve beads CLI commands (research-step skill uses bd dozens of times per session)

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

if [[ "$COMMAND" == bd\ * ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
  exit 0
fi

echo '{}'
