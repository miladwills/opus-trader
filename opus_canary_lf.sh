#!/bin/bash
# Opus Trader Automated Canary Script
set -euo pipefail

DURATION_MINUTES=${1:-90}
STOP_ON_ALERT=${2:-1}
LOG_FILE="/var/www/opus_trader/storage/runner.log"
ALERT_FILE="/var/www/opus_trader/storage/alerts.log"
REPORT_FILE="/var/www/opus_trader/storage/canary_report.txt"
STORAGE_DIR="/var/www/opus_trader/storage"

# Ensure directories and files exist
mkdir -p "$STORAGE_DIR"
touch "$LOG_FILE" "$ALERT_FILE" "$REPORT_FILE"

START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "[$START_TS] Canary session started: duration=${DURATION_MINUTES}m, stop_on_alert=${STOP_ON_ALERT}" >> "$REPORT_FILE"

# Restart services
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Restarting services..." >> "$REPORT_FILE"
systemctl restart opus_trader
systemctl restart opus_runner
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Services restarted successfully" >> "$REPORT_FILE"

# Patterns to watch
PATTERNS="UNATTRIBUTED|retCode 110072|API INSTABILITY|order_link_id=None|Failed to fetch account equity|TypeError|Traceback"

# Signal file for alerts
ALERT_FOUND_FILE=$(mktemp)
trap "rm -f $ALERT_FOUND_FILE" EXIT

# Background monitoring
(
    tail -F -n0 "$LOG_FILE" | while read -r line; do
        if echo "$line" | grep -Ei "$PATTERNS" > /dev/null; then
            TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
            MSG="[$TS] ALERT FOUND: $line"
            echo "$MSG" >> "$ALERT_FILE"
            echo "$MSG" >> "$REPORT_FILE"
            echo "1" > "$ALERT_FOUND_FILE"
            
            if [ "$STOP_ON_ALERT" -eq 1 ]; then
                echo "[$TS] STOP_ON_ALERT enabled - halting services immediately!" >> "$REPORT_FILE"
                systemctl stop opus_trader opus_runner
                kill -USR1 $$
            fi
        fi
    done
) &
MONITOR_PID=$!

# Handle USR1 for early exit
trap "kill $MONITOR_PID 2>/dev/null || true; exit 42" USR1

# Timer
END_TIME=$(( $(date +%s) + DURATION_MINUTES * 60 ))
while [ $(date +%s) -lt $END_TIME ]; do
    if ! kill -0 $MONITOR_PID 2>/dev/null; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Monitoring process died" >> "$REPORT_FILE"
        exit 1
    fi
    sleep 2
done

# Cleanup
kill $MONITOR_PID 2>/dev/null || true
FINISH_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ -s "$ALERT_FOUND_FILE" ]; then
    echo "[$FINISH_TS] Canary finished with ALERTS detected." >> "$REPORT_FILE"
    exit 42
else
    echo "[$FINISH_TS] Canary finished successfully - NO alerts detected." >> "$REPORT_FILE"
    exit 0
fi
