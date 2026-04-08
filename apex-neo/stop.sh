#!/usr/bin/env bash
# Apex NEO — Graceful shutdown
set -euo pipefail

echo "=== Stopping Apex NEO ==="

# Send SIGTERM to the Python process inside screen
PIDS=$(pgrep -f "python3 main.py" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "Sending SIGTERM to PID(s): $PIDS"
    kill -TERM $PIDS 2>/dev/null || true
    sleep 2
    # Force kill if still running
    REMAINING=$(pgrep -f "python3 main.py" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
        echo "Force killing PID(s): $REMAINING"
        kill -9 $REMAINING 2>/dev/null || true
    fi
else
    echo "No running process found"
fi

# Kill screen session
screen -S apex-neo -X quit 2>/dev/null || true

echo "Stopped."
