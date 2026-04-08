#!/usr/bin/env bash
# Apex NEO — One-command setup for Ubuntu 24.04
set -euo pipefail

echo "=== Apex NEO Setup ==="

# System dependencies
echo "[1/5] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv screen curl > /dev/null 2>&1

# Python virtual environment
echo "[2/5] Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# Python dependencies
echo "[3/5] Installing Python packages..."
pip install --upgrade pip -q
pip install -q \
    "ccxt>=4.4.0" \
    "httpx>=0.27.0" \
    "numpy>=2.0.0" \
    "orjson>=3.9.0" \
    "loguru>=0.7.0" \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "python-dotenv>=1.0.0" \
    "uvloop>=0.19.0; sys_platform != 'win32'"

# Environment file
echo "[4/5] Setting up configuration..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  Created .env from template — please edit with your API keys"
else
    echo "  .env already exists, skipping"
fi

# Data directories
echo "[5/5] Creating data directories..."
mkdir -p logs data

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your Binance API key and Telegram token"
echo "  2. Run: ./start.sh"
echo "  3. Open: http://YOUR_IP:8080"
echo ""
