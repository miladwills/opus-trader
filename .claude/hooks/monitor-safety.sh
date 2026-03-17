#!/usr/bin/env bash
# PreToolUse hook: Block destructive Bash commands when monitor-agent is active.
# Checks for /tmp/opus_monitor_active lock file. If absent, allows everything.
# If present, only read-only commands are permitted.

set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only check Bash commands
if [ "$TOOL_NAME" != "Bash" ]; then
  exit 0
fi

# If monitor lock file doesn't exist, allow everything
if [ ! -f /tmp/opus_monitor_active ]; then
  exit 0
fi

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Extract first meaningful command (before pipes, semicolons, &&)
FIRST_CMD=$(echo "$COMMAND" | sed 's/[|;&].*//' | awk '{print $1}' | sed 's|.*/||')

# Allowed read-only commands
ALLOWED_CMDS=(
  cat tail head grep rg less more wc
  ls stat file find du df
  ps top htop pgrep lsof
  date uptime hostname
  systemctl  # status/is-active only, checked below
  journalctl
  jq python3  # for parsing only, checked below
  sort uniq tr cut sed awk
  diff
  git  # read-only git commands only
)

# Check if command is in allowed list
IS_ALLOWED=false
for ALLOWED in "${ALLOWED_CMDS[@]}"; do
  if [ "$FIRST_CMD" = "$ALLOWED" ]; then
    IS_ALLOWED=true
    break
  fi
done

if [ "$IS_ALLOWED" = false ]; then
  cat <<EOF
{"hookEventName":"PreToolUse","permissionDecision":"deny","reason":"MONITOR SAFETY: Command '$FIRST_CMD' is blocked while monitor-agent is active. Only read-only commands are allowed. Remove /tmp/opus_monitor_active to disable this check."}
EOF
  exit 0
fi

# Extra checks for commands that have destructive subcommands
case "$FIRST_CMD" in
  systemctl)
    # Only allow status, is-active, is-enabled, list-units, list-unit-files
    if echo "$COMMAND" | grep -qE 'restart|stop|start|reload|enable|disable|daemon-reload|kill'; then
      cat <<EOF
{"hookEventName":"PreToolUse","permissionDecision":"deny","reason":"MONITOR SAFETY: systemctl destructive subcommand blocked while monitor-agent is active. Only status/is-active queries allowed."}
EOF
      exit 0
    fi
    ;;
  git)
    # Only allow read-only git commands
    if echo "$COMMAND" | grep -qE 'push|commit|reset|checkout|merge|rebase|cherry-pick|stash|clean|branch -[dD]'; then
      cat <<EOF
{"hookEventName":"PreToolUse","permissionDecision":"deny","reason":"MONITOR SAFETY: Destructive git command blocked while monitor-agent is active."}
EOF
      exit 0
    fi
    ;;
  python3)
    # Block if it looks like it's running a script (not just parsing)
    if echo "$COMMAND" | grep -qE 'import os|subprocess|shutil|open\(.*w'; then
      cat <<EOF
{"hookEventName":"PreToolUse","permissionDecision":"deny","reason":"MONITOR SAFETY: Python command with write operations blocked while monitor-agent is active."}
EOF
      exit 0
    fi
    ;;
esac

exit 0
