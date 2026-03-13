#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Setting up vigilant-system ==="

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "Running tests..."
python -m pytest tests/ -v --tb=short

echo ""
echo "=== Setup complete ==="
echo "Activate with: source .venv/bin/activate"
