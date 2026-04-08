#!/usr/bin/env bash
# Start PREDATOR v4 in screen session
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-paper}"

[ -f .venv/bin/activate ] && source .venv/bin/activate

echo "=== PREDATOR v4 TOKYO ==="
echo "Mode: $MODE"
echo "Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):8080"

screen -S predator -X quit 2>/dev/null || true
screen -dmS predator bash -c "cd $(pwd) && source .venv/bin/activate && python3 main.py --mode $MODE 2>&1 | tee logs/console.log"

echo "Started in screen 'predator'"
echo "  Attach:  screen -r predator"
echo "  Detach:  Ctrl-A, D"
echo "  Stop:    ./stop.sh"
