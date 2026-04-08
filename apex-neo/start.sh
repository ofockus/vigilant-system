#!/usr/bin/env bash
# Apex NEO — Start in a screen session
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

MODE="${1:-observe}"

echo "=== Starting Apex NEO ==="
echo "Mode: $MODE"
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8080"
echo ""

# Kill existing session if running
screen -S apex-neo -X quit 2>/dev/null || true

# Start in screen
screen -dmS apex-neo bash -c "cd $SCRIPT_DIR && source .venv/bin/activate && python3 main.py --mode $MODE 2>&1 | tee logs/console.log"

echo "Started in screen session 'apex-neo'"
echo "  Attach: screen -r apex-neo"
echo "  Detach: Ctrl-A, D"
echo "  Stop:   ./stop.sh"
