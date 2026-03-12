---
name: binance
description: Normalize Binance market context from scanner/fusion payloads so downstream modules consume a stable exchange contract.
---

# Binance Skill

Use this skill to standardize market data before execution logic.

## Inputs
- `market.primary_symbol`
- `market.path`
- `market.net_pct`
- `market.net_usd`
- `market.quote_volume_total`
- `market.market_active`
- `market.market_spot`

## Output contract
```json
{
  "exchange": "binance",
  "symbol": "BTCUSDT",
  "path": "USDT→BTC→ETH→USDT",
  "net_pct": 0.0,
  "net_usd": 0.0,
  "quote_volume_total": 0.0,
  "market_active": true,
  "market_spot": true
}
```
