#!/usr/bin/env python3
"""
PREDATOR v4 TOKYO — Entry point.

Usage:
    python main.py                    # paper mode (default from config)
    python main.py --mode paper       # paper trading
    python main.py --mode live        # live (requires confirmation)
    python main.py --mode backtest    # run backtest
    python main.py --download         # download historical data only
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from predator.config import load_config
from predator.utils import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PREDATOR v4 TOKYO")
    parser.add_argument("--mode", choices=["backtest", "paper", "live"], default=None)
    parser.add_argument("--config", type=str, default=None, help="Config YAML path")
    parser.add_argument("--download", action="store_true", help="Download data only")
    parser.add_argument("--symbol", type=str, default=None, help="Single symbol for backtest")
    return parser.parse_args()


async def run_backtest(cfg) -> None:
    """Download data if needed, then run tick-level backtest."""
    from predator.backtest.data import download_all, download_agg_trades
    from predator.backtest.engine import BacktestEngine, print_report
    from predator.strategy.exits import ExitManager
    from predator.strategy.features import FeatureEngine
    from predator.strategy.model import PredictorModel
    from predator.strategy.signals import SignalGenerator

    symbols = cfg.symbols.pool[:cfg.symbols.max_active]
    data_dir = cfg.backtest.data_dir

    # Download data
    await download_all(symbols, days=cfg.backtest.lookback_days, data_dir=data_dir)

    # Build strategy components
    signal_gen = SignalGenerator(
        min_confirmations=cfg.strategy.min_confirmations,
        min_model_confidence=cfg.strategy.min_model_confidence,
        min_book_imbalance=cfg.strategy.min_book_imbalance,
        min_flow_delta=cfg.strategy.min_flow_delta,
        decel_threshold=cfg.strategy.decel_threshold,
        ek_rev_threshold=cfg.strategy.ek_rev_threshold,
    )
    exit_mgr = ExitManager(
        min_hold_s=cfg.exit.min_hold_s,
        cooldown_s=cfg.exit.cooldown_s,
        stop_loss_pct=cfg.exit.stop_loss_pct,
        take_profit_base_pct=cfg.exit.take_profit_base_pct,
        trail_activation_pct=cfg.exit.trail_activation_pct,
        trail_callback_pct=cfg.exit.trail_callback_pct,
        max_hold_s=cfg.exit.max_hold_s,
        time_decay_start_s=cfg.exit.time_decay_start_s,
    )
    model = PredictorModel()
    model.load()  # Load if exists, else heuristic fallback

    engine = BacktestEngine(
        initial_capital=cfg.backtest.initial_capital,
        latency_ms=cfg.backtest.latency_ms,
        slippage_pct=cfg.backtest.slippage_pct,
        maker_fee_pct=cfg.backtest.maker_fee_pct,
        taker_fee_pct=cfg.backtest.taker_fee_pct,
    )

    # Run backtest for each symbol
    for sym in symbols:
        trades_path = Path(data_dir) / f"{sym}_aggTrades.parquet"
        if not trades_path.exists():
            continue

        from loguru import logger
        logger.info("Running backtest for {}", sym)
        result = engine.run(
            trades_path, signal_gen, exit_mgr, model,
            FeatureEngine(
                momentum_window=cfg.strategy.momentum_window_ticks,
                flow_window=cfg.strategy.flow_window_ticks,
            ),
        )
        print_report(result)


async def run_live(cfg) -> None:
    """Run paper or live trading."""
    from predator.core import Predator

    pred = Predator(cfg)

    # Handle signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, pred._request_stop)

    await pred.start()


async def run_download(cfg) -> None:
    """Download data only."""
    from predator.backtest.data import download_all

    symbols = cfg.symbols.pool[:cfg.symbols.max_active]
    await download_all(symbols, days=cfg.backtest.lookback_days,
                       data_dir=cfg.backtest.data_dir)


async def main() -> None:
    args = parse_args()

    config_path = Path(args.config) if args.config else None
    cfg = load_config(config_path)

    if args.mode:
        cfg.mode = args.mode

    setup_logging(cfg.log.dir, cfg.log.level)

    # Safety: live mode confirmation
    if cfg.mode == "live":
        print("\n" + "=" * 50)
        print("  WARNING: LIVE TRADING MODE")
        print(f"  Testnet: {cfg.exchange.binance_testnet}")
        print(f"  Capital: ${cfg.risk.starting_capital}")
        print("=" * 50)
        confirm = input("Type 'CONFIRM LIVE' to proceed: ")
        if confirm.strip() != "CONFIRM LIVE":
            print("Aborted.")
            sys.exit(0)

    if args.download:
        await run_download(cfg)
    elif cfg.mode == "backtest":
        await run_backtest(cfg)
    else:
        await run_live(cfg)


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass

    asyncio.run(main())
