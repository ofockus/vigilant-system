"""
Tick-level backtest engine.

Replays historical aggTrades through the full strategy pipeline:
features → model → signals → exits → risk management.
Simulates realistic latency, slippage, and maker/taker fees.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from ..strategy.exits import ExitManager, PositionState
from ..strategy.features import FeatureEngine, FeatureVector
from ..strategy.model import PredictorModel
from ..strategy.signals import SignalGenerator


@dataclass
class BacktestTrade:
    symbol: str
    side: int
    entry_price: float
    exit_price: float
    qty: float
    leverage: int
    pnl_pct: float
    pnl_usd: float
    fees: float
    entry_time: float
    exit_time: float
    hold_time_s: float
    exit_reason: str


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    initial_capital: float = 200.0
    final_equity: float = 200.0
    peak_equity: float = 200.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    avg_hold_s: float = 0.0
    total_fees: float = 0.0
    equity_curve: list[tuple[float, float]] = field(default_factory=list)


class BacktestEngine:
    """Tick-level replay backtester."""

    def __init__(
        self,
        initial_capital: float = 200.0,
        latency_ms: float = 3.0,
        slippage_pct: float = 0.005,
        maker_fee_pct: float = 0.02,
        taker_fee_pct: float = 0.04,
        leverage: int = 10,
    ) -> None:
        self.capital = initial_capital
        self.latency_ms = latency_ms
        self.slippage_pct = slippage_pct
        self.maker_fee = maker_fee_pct
        self.taker_fee = taker_fee_pct
        self.default_leverage = leverage

    def run(
        self,
        trades_path: Path,
        signal_gen: SignalGenerator,
        exit_mgr: ExitManager,
        model: PredictorModel,
        feature_engine: FeatureEngine | None = None,
        max_trades: int = 0,
    ) -> BacktestResult:
        """Run backtest on historical trade data."""
        logger.info("Loading trades from {}", trades_path)
        df = pd.read_parquet(trades_path)
        df = df.sort_values("timestamp").reset_index(drop=True)
        logger.info("Loaded {} trades ({:.1f} days)",
                    len(df), (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]) / 86400)

        sym = trades_path.stem.split("_")[0].lower()
        fe = feature_engine or FeatureEngine()

        result = BacktestResult(initial_capital=self.capital)
        equity = self.capital
        peak = equity
        position: PositionState | None = None
        trade_labels_X: list[np.ndarray] = []
        trade_labels_y: list[int] = []

        # Simulate orderbook from trade flow (simplified: bid = price - spread/2)
        spread_ema = 0.0
        last_price = 0.0

        tick_interval = max(len(df) // 10000, 100)  # sample for speed
        processed = 0

        for idx in range(0, len(df), max(1, len(df) // 50000)):
            row = df.iloc[idx]
            price = row["price"]
            qty = row["qty"]
            is_buy = not row["is_buyer_maker"]  # aggressor side
            ts = row["timestamp"]

            if price <= 0:
                continue

            # Simulated spread
            if last_price > 0:
                tick_change = abs(price - last_price) / last_price
                spread_ema = spread_ema * 0.99 + tick_change * 0.01
            last_price = price

            spread_pct = max(spread_ema * 100, 0.001)

            # Feed feature engine
            fe.add_trade(sym, price, qty, is_buy, ts)
            fe.add_kline(sym, price, price * 1.0001, price * 0.9999)

            # Compute features (not every tick for speed)
            processed += 1
            if processed % 5 != 0:
                continue

            # Synthetic book levels
            half_spread = price * spread_pct / 200
            bids = [(price - half_spread * (i + 1), qty * (10 - i)) for i in range(10)]
            asks = [(price + half_spread * (i + 1), qty * (10 - i)) for i in range(10)]

            fv = fe.compute(sym, bids, asks, spread_pct)

            # --- Check exit if in position ---
            if position is not None:
                direction, conf = model.predict(fv)
                exit_dec = exit_mgr.check(position, fv, price, direction)

                if exit_dec.should_exit:
                    # Apply slippage + fees
                    slip = self.slippage_pct / 100
                    if position.side == 1:
                        exit_price = price * (1 - slip)
                        pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100
                    else:
                        exit_price = price * (1 + slip)
                        pnl_pct = (position.entry_price - exit_price) / position.entry_price * 100

                    # Fees (entry + exit)
                    fee_pct = self.taker_fee * 2
                    pnl_pct -= fee_pct
                    notional = position.qty * position.entry_price
                    pnl_usd = pnl_pct / 100 * notional
                    fees = fee_pct / 100 * notional

                    trade = BacktestTrade(
                        symbol=sym, side=position.side,
                        entry_price=position.entry_price,
                        exit_price=exit_price, qty=position.qty,
                        leverage=position.leverage,
                        pnl_pct=pnl_pct, pnl_usd=pnl_usd, fees=fees,
                        entry_time=position.entry_time, exit_time=ts,
                        hold_time_s=ts - position.entry_time,
                        exit_reason=exit_dec.reason,
                    )
                    result.trades.append(trade)

                    # ML training label
                    label = 1 if pnl_pct > 0 else -1 if pnl_pct < -0.02 else 0
                    trade_labels_y.append(label)

                    equity += pnl_usd
                    peak = max(peak, equity)
                    result.equity_curve.append((ts, equity))
                    position = None
                    exit_mgr.record_exit()

                    if max_trades and len(result.trades) >= max_trades:
                        break

                continue

            # --- Check entry if flat ---
            if exit_mgr.on_cooldown:
                continue

            direction, confidence = model.predict(fv)
            signal = signal_gen.evaluate(fv, direction, confidence)

            if signal.direction != 0:
                # Apply entry slippage
                slip = self.slippage_pct / 100
                entry_price = price * (1 + slip) if signal.direction == 1 else price * (1 - slip)

                # Position sizing (simplified for backtest)
                risk_usd = equity * 0.0075  # 0.75%
                notional = risk_usd / (0.09 / 100)  # risk / SL
                notional = min(notional, equity * self.default_leverage * 0.9)
                qty = notional / entry_price

                position = PositionState(
                    symbol=sym, side=signal.direction,
                    entry_price=entry_price, entry_time=ts,
                    qty=qty, leverage=self.default_leverage,
                )
                # Save features for ML training
                trade_labels_X.append(fv.to_array())

        # --- Compile results ---
        result.final_equity = equity
        result.peak_equity = peak
        result.total_trades = len(result.trades)

        if result.trades:
            pnls = [t.pnl_pct for t in result.trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            result.win_rate = len(wins) / len(pnls) * 100
            result.profit_factor = sum(wins) / abs(sum(losses)) if losses else float("inf")
            result.avg_hold_s = sum(t.hold_time_s for t in result.trades) / len(result.trades)
            result.total_fees = sum(t.fees for t in result.trades)

            # Max drawdown from equity curve
            eq = [e for _, e in result.equity_curve]
            if eq:
                peak_arr = np.maximum.accumulate(eq)
                dd = (peak_arr - eq) / peak_arr * 100
                result.max_drawdown_pct = float(np.max(dd))

            # Sharpe ratio (annualized from per-trade returns)
            if len(pnls) > 1:
                pnl_arr = np.array(pnls)
                result.sharpe_ratio = float(
                    pnl_arr.mean() / (pnl_arr.std() + 1e-10) * np.sqrt(252 * 24)
                )

        # Train model on labeled data
        if trade_labels_X and trade_labels_y and len(trade_labels_X) == len(trade_labels_y):
            X = np.array(trade_labels_X)
            y = np.array(trade_labels_y)
            if len(X) >= 50:
                logger.info("Training model on {} labeled trades", len(X))
                model.train(X, y)
                model.save()

        return result


def print_report(result: BacktestResult) -> str:
    """Format backtest results as a report string."""
    lines = [
        "=" * 55,
        "  PREDATOR v4 BACKTEST REPORT",
        "=" * 55,
        f"  Initial Capital:    ${result.initial_capital:.2f}",
        f"  Final Equity:       ${result.final_equity:.2f}",
        f"  Return:             {(result.final_equity/result.initial_capital - 1)*100:+.2f}%",
        f"  Peak Equity:        ${result.peak_equity:.2f}",
        f"  Max Drawdown:       {result.max_drawdown_pct:.2f}%",
        "-" * 55,
        f"  Total Trades:       {result.total_trades}",
        f"  Win Rate:           {result.win_rate:.1f}%",
        f"  Profit Factor:      {result.profit_factor:.2f}",
        f"  Sharpe Ratio:       {result.sharpe_ratio:.2f}",
        f"  Avg Hold Time:      {result.avg_hold_s:.1f}s",
        f"  Total Fees:         ${result.total_fees:.4f}",
        "-" * 55,
    ]

    if result.trades:
        pnls = [t.pnl_pct for t in result.trades]
        lines.extend([
            f"  Avg Win:            {np.mean([p for p in pnls if p > 0]):.4f}%"
            if any(p > 0 for p in pnls) else "  Avg Win:            N/A",
            f"  Avg Loss:           {np.mean([p for p in pnls if p <= 0]):.4f}%"
            if any(p <= 0 for p in pnls) else "  Avg Loss:           N/A",
        ])

        # Exit reason breakdown
        reasons: dict[str, int] = {}
        for t in result.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        lines.append("-" * 55)
        lines.append("  Exit Reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            lines.append(f"    {reason:20s} {count:5d} ({count/result.total_trades*100:.1f}%)")

    lines.append("=" * 55)
    report = "\n".join(lines)
    logger.info("\n{}", report)
    return report
