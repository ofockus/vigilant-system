#!/usr/bin/env bash
# PREDATOR v4 TOKYO — VPS Setup (Ubuntu 24.04, Contabo Tokyo)
set -euo pipefail

echo "=== PREDATOR v4 TOKYO — VPS Setup ==="

# System packages
echo "[1/6] System packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3.12 python3.12-venv python3-pip screen htop curl git > /dev/null 2>&1

# Python venv
echo "[2/6] Python virtual environment..."
python3.12 -m venv .venv
source .venv/bin/activate

# Dependencies
echo "[3/6] Python dependencies..."
pip install --upgrade pip -q
pip install -q -r requirements.txt

# Environment
echo "[4/6] Environment setup..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  >>> Created .env — EDIT THIS with your API keys!"
else
    echo "  .env exists, skipping"
fi

# Directories
echo "[5/6] Data directories..."
mkdir -p logs data/historical data

# Permissions
echo "[6/6] Script permissions..."
chmod +x start.sh stop.sh

echo ""
echo "=== Setup Complete ==="
echo ""
echo "NEXT STEPS:"
echo "  1. nano .env                     # Add API keys"
echo "  2. nano config.yaml              # Tune parameters"
echo "  3. ./start.sh backtest           # Run backtest first"
echo "  4. ./start.sh paper              # Then paper trade"
echo "  5. ./start.sh live               # Only after consistent profit"
echo ""
echo "DASHBOARD: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
