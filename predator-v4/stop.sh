#!/usr/bin/env bash
# Graceful shutdown
set -euo pipefail

echo "Stopping PREDATOR v4..."
PIDS=$(pgrep -f "python3 main.py" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    kill -TERM $PIDS 2>/dev/null || true
    sleep 2
    REMAINING=$(pgrep -f "python3 main.py" 2>/dev/null || true)
    [ -n "$REMAINING" ] && kill -9 $REMAINING 2>/dev/null || true
fi
screen -S predator -X quit 2>/dev/null || true
echo "Stopped."
