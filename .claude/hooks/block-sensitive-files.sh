#!/usr/bin/env bash
# PreToolUse hook: Block edits to sensitive trading-core files unless explicitly requested.
# Reads hook JSON from stdin, checks file_path against protected list.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Normalize to relative path from project root
REL_PATH="${FILE_PATH#/var/www/}"

BLOCKED_FILES=(
  # Core trading files (CLAUDE.md §Sensitive Areas, bullet 5)
  "services/grid_bot_service.py"
  "runner.py"
  "app.py"
  # Config / credentials (§Sensitive Areas, bullet 3)
  "config/config.py"
  "config/strategy_config.py"
  # Order execution & routing (§Sensitive Areas, bullet 4)
  "services/bybit_client.py"
  "services/order_router_service.py"
  # Risk & margin (§Sensitive Areas, bullet 4)
  "services/risk_manager_service.py"
  "services/margin_monitor_service.py"
  # PnL accounting & attribution (§Sensitive Areas, bullet 4)
  "services/pnl_service.py"
  "services/order_ownership_service.py"
  # Bot lifecycle & state persistence (§Sensitive Areas, bullets 2+4)
  "services/bot_manager_service.py"
  "services/bot_storage_service.py"
)

for BLOCKED in "${BLOCKED_FILES[@]}"; do
  if [ "$REL_PATH" = "$BLOCKED" ]; then
    cat <<EOF
{"hookEventName":"PreToolUse","permissionDecision":"deny","reason":"Blocked: ${BLOCKED} is a sensitive trading-core file. Edits require explicit user request. Ask the user before modifying this file."}
EOF
    exit 0
  fi
done

exit 0
