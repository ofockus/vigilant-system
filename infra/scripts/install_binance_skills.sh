#!/usr/bin/env bash
set -euo pipefail

INSTALLER="/opt/codex/skills/.system/skill-installer/scripts/install-skill-from-github.py"
REPO="binance/binance-skills-hub"

PATHS=(
  "skills/binance-web3/query-address-info"
  "skills/binance-web3/meme-rush"
  "skills/binance-web3/trading-signal"
  "skills/binance-web3/query-token-audit"
  "skills/binance-web3/crypto-market-rank"
  "skills/binance-web3/query-token-info"
  "skills/binance/derivatives-trading-usds-futures"
  "skills/binance/square-post"
  "skills/binance/assets"
  "skills/binance/margin-trading"
  "skills/binance/spot"
  "skills/binance/alpha"
)

for p in "${PATHS[@]}"; do
  echo "[install] $p"
  python "$INSTALLER" --repo "$REPO" --path "$p" || true
done

echo "Done. Restart Codex to pick up new skills."
