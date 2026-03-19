#!/bin/bash
# Auto-approve Read/Write/Edit operations on ~/.asta/ directories

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""')

# Expand ~ to $HOME for comparison
EXPANDED_PATH="${FILE_PATH/#\~/$HOME}"

# Check if path is under ~/.asta/ (handles both ~/... and /Users/.../... forms)
if [[ "$EXPANDED_PATH" == "$HOME/.asta/"* ]] || [[ "$FILE_PATH" == *"/.asta/"* ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
else
  echo '{}'
fi
