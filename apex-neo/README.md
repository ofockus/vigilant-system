# Apex NEO

Production-grade crypto trading system. Single Python process, 9 signal layers,
live dashboard, Telegram integration.

## Quick Start

```bash
# 1. Setup (Ubuntu 24.04)
chmod +x setup.sh start.sh stop.sh
./setup.sh

# 2. Configure
nano .env  # Add your Binance API key + Telegram token

# 3. Run (observe mode — safe, read-only)
./start.sh observe

# 4. Open dashboard
# http://YOUR_VPS_IP:8080
```

## Modes

| Mode | Description |
|------|-------------|
| `observe` | Read-only. Logs signals and hypothetical trades. Default. |
| `paper` | Simulated fills with realistic slippage. No real orders. |
| `live` | Real orders. Requires confirmation prompt. |

## Signal Layers

| Layer | Module | Function |
|-------|--------|----------|
| L1 | `engine/predictor.py` | OU mean-reversion + momentum |
| L2 | `engine/physics.py` | F=ma, velocity, gravity, kinetic energy |
| L3 | `engine/toxicity.py` | VPIN toxicity + liquidation cascade |
| L4 | `engine/shield.py` | Ghost walls, spoofing, adaptive jitter |
| L5 | `engine/cross_intel.py` | Cross-exchange funding divergence |
| L6 | `engine/drift.py` | ADWIN concept drift detection |
| L7 | `engine/calibrator.py` | Kalman + Kelly + EMA recalibration |
| L8 | `engine/flow.py` | Order flow imbalance |
| L9 | `engine/whale.py` | Whale detection + classification |

## Exit Logic

Hard exits (always immediate):
- Stop loss: 0.12%
- VPIN critical: >90%
- Liquidation cascade

Soft exits (blocked before 15s min hold):
- Deceleration > 0.20
- Trailing stop: 0.06%–0.12% (velocity-scaled)
- Signal flip

## Commands

```bash
./start.sh          # Start in observe mode
./start.sh paper    # Start in paper mode
./start.sh live     # Start in live mode (confirmation required)
./stop.sh           # Graceful shutdown
screen -r apex-neo  # Attach to console
```

## Telegram Commands

| Command | Action |
|---------|--------|
| `/status` | Full system status |
| `/pnl` | Current PnL and risk stats |
| `/equity` | Current equity |
| `/kill` | Shutdown the bot |
| `/resume` | Resume after pause |

## File Structure

```
apex-neo/
├── main.py           # Orchestrator
├── config.py         # Configuration
├── engine/           # 9 signal layers
├── trading/          # Connector, executor, risk, regime
├── dashboard/        # FastAPI + WebSocket UI
├── telegram/         # Telegram bot
└── utils/            # Logging, journal
```
