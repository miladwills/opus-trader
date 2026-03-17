#!/usr/bin/env bash
# PostToolUse hook: Run py_compile on edited Python files to catch syntax errors immediately.
# Reads hook JSON from stdin.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only check Python files
if [[ "$FILE_PATH" != *.py ]]; then
  exit 0
fi

# Check file exists before compiling
if [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# Run syntax check (use mktemp to avoid collisions)
ERRFILE=$(mktemp /tmp/pycompile_err.XXXXXX)
trap 'rm -f "$ERRFILE"' EXIT
if ! /var/www/venv/bin/python -m py_compile "$FILE_PATH" 2>"$ERRFILE"; then
  ERROR=$(cat "$ERRFILE")
  cat <<EOF
{"hookEventName":"PostToolUse","blocked":true,"reason":"Python syntax error in ${FILE_PATH}:\n${ERROR}\nFix the syntax error before continuing."}
EOF
  exit 0
fi

exit 0
