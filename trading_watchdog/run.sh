#!/usr/bin/env bash
# Trading Watchdog v1 — Start script
# Usage: ./run.sh [--port PORT]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRADER_ROOT="${SCRIPT_DIR}/.."
export PYTHONPATH="${TRADER_ROOT}"

# Use venv if available
PYTHON=python3
if [ -f "${TRADER_ROOT}/venv/bin/python3" ]; then
    PYTHON="${TRADER_ROOT}/venv/bin/python3"
fi

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) export TW_PORT="$2"; shift 2 ;;
        --debug) export TW_DEBUG=1; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "Starting Trading Watchdog v1 on port ${TW_PORT:-8200}..."
exec "${PYTHON}" -m trading_watchdog.app
