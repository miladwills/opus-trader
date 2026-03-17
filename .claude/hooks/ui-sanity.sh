#!/usr/bin/env bash
# PostToolUse hook: Remind model to verify UI sanity after editing frontend files.
# Reads hook JSON from stdin.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only trigger for frontend files
if [[ "$FILE_PATH" == *.html || "$FILE_PATH" == *.css || "$FILE_PATH" == *.js ]]; then
  cat <<EOF
{"hookEventName":"PostToolUse","additionalContext":"UI file modified (${FILE_PATH##*/}). Verify: (1) no text overlap or clipping, (2) no overflow on narrow/mobile screens, (3) no broken responsive layout, (4) no unnecessary full rerender for live-updating elements, (5) CSS brace balance if editing embedded styles."}
EOF
  exit 0
fi

exit 0
