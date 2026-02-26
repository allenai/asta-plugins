#!/bin/bash
# Auto-approve Bash commands that operate on ~/.asta/ directories or use asta CLI

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

# Auto-approve asta CLI commands (literature and papers)
if [[ "$COMMAND" == asta\ * ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
  exit 0
fi

# Auto-approve curl to theorizer endpoint
if [[ "$COMMAND" == curl*"ai2-reviz--theorizer"* ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
  exit 0
fi

# Auto-approve python3 scripts for artifact export on ~/.asta/ paths
if [[ "$COMMAND" == python3* ]] && [[ "$COMMAND" == *"/.asta/"* ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
  exit 0
fi

# Auto-approve pip install for asta-sdk
if [[ "$COMMAND" == "pip install"*"asta-sdk"* ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
  exit 0
fi

# Check if command references ~/.asta/ or $HOME/.asta/ paths
if [[ "$COMMAND" == *"/.asta/"* ]] || [[ "$COMMAND" == *'~/.asta/'* ]]; then
  # Additional safety: only approve read-only commands like jq, cat, ls
  # or directory creation like mkdir
  if [[ "$COMMAND" == jq* ]] || [[ "$COMMAND" == "mkdir -p ~/.asta"* ]] || [[ "$COMMAND" == *"| jq"* ]]; then
    echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
    exit 0
  fi
fi

echo '{}'
