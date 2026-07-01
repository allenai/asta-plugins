#!/bin/bash
# Auto-approve any tool operation targeting a .asta/ directory under
# the user's home directory ($HOME / ~) or the current working directory.
# Handles Read/Write/Edit via file_path/path and Bash via the command string.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

# Expand a leading ~ in FILE_PATH for the home-directory check.
EXPANDED_PATH="${FILE_PATH/#\~/$HOME}"

# FILE_PATH: under HOME (after ~ expansion) or CWD-relative.
if [[ "$EXPANDED_PATH" == "$HOME/.asta/"* ]] \
   || [[ "$FILE_PATH" == ".asta/"* ]] \
   || [[ "$FILE_PATH" == "./.asta/"* ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
  exit 0
fi

# COMMAND: a token (at start or after whitespace) that names .asta/ under
# HOME (~/.asta/ or $HOME/.asta/) or CWD (.asta/ or ./.asta/).
if [[ "$COMMAND" =~ (^|[[:space:]])(~/|${HOME}/|\./)?\.asta/ ]]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
  exit 0
fi

echo '{}'
