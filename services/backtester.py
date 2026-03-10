# ===================================================================
# APEX CITADEL v3 — TICK-LEVEL BACKTESTER
#
# Replays real or synthetic L2 tick data through the full APM engine.
# This is NOT a candle backtester — every tick fires all 4 weapons
# (VPIN, OBI Trail, Ghost Liquidity, Alpha Decay) exactly as they
# run in production.
#
# Capabilities:
#   1. Load tick data from CSV / Parquet / synthetic generator
#   2. Generate entry signals from configurable strategies
#   3. Replay every tick through APM.process_tick()
#   4. Full analytics: PnL, Sharpe, max drawdown, win rate,
#      exit reason breakdown, equity curve
#   5. Parameter sweep / grid search for APM tuning
#   6. Export results to JSON/CSV for Streamlit dashboards
#
# Usage:
#   engine = BacktestEngine()
#   engine.load_ticks("SOL_USDT_ticks.csv")
#   engine.set_strategy(MomentumStrategy(lookback=20))
#   results = await engine.run()
#   results.summary()
#   results.export("results.json")
# ===================================================================

from __future__ import annotations

import asyncio
import csv
import json
import math
import os
import statistics
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from apm import (
    ActivePositionManager,
    APMDecision,
    ExitReason,
    ManagedPosition,
    TickData,
    VPINComputer,
    DynamicOBITrail,
    GhostLiquidityReactor,
    AlphaDecayTimer,
    VPIN_TOXIC_THRESHOLD,
    ALPHA_DECAY_S,
    ALPHA_MIN_MOVE_PCT,
)
from apex_common.logging import get_logger

log = get_logger("backtester")


# ════════════════════════════════════════════════════
# TICK DATA MODEL
# ════════════════════════════════════════════════════

@dataclass
class RawTick:
    """A single tick from the data source."""
    timestamp_ms: int        # unix ms
    price: float
    volume: float = 0.0
    obi: float = 0.0         # order book imbalance [-1, 1]
    bid_depth: float = 0.0   # total bid depth USD
    ask_depth: float = 0.0   # total ask depth USD
    ghost_events: list = field(default_factory=list)
    macro_kill: bool = False

    def to_tick_data(self) -> TickData:
        """Convert to APM's native TickData."""
        return TickData(
            price=self.price,
            volume=self.volume,
            obi=self.obi,
            ghost_events=self.ghost_events,
            macro_kill=self.macro_kill,
        )


# ════════════════════════════════════════════════════
# SYNTHETIC TICK GENERATOR
# ════════════════════════════════════════════════════

class SyntheticTickGenerator:
    """Generates realistic tick data with configurable scenarios.
    
    Scenarios:
      - pump_dump: clean pump then crash (tests alpha decay + trail)
      - slow_bleed: gradual sell-off (tests VPIN + trail tightening)
      - chop: sideways noise (tests alpha decay + time limit)
      - ghost_rug: liquidity pulled mid-pump (tests ghost reactor)
      - clean_pump: steady upward (tests take profit)
      - vpin_toxic: informed selling pressure building (tests VPIN)
      - mixed: random mix of all above
    """

    SCENARIOS = [
        "pump_dump", "slow_bleed", "chop", "ghost_rug",
        "clean_pump", "vpin_toxic", "mixed",
    ]

    def __init__(self, seed: int = 42):
        import random
        self._rng = random.Random(seed)

    def generate(
        self,
        scenario: str = "mixed",
        n_ticks: int = 2000,
        start_price: float = 100.0,
        tick_interval_ms: int = 100,
        symbol: str = "SYN/USDT",
    ) -> List[RawTick]:
        """Generate a sequence of ticks for a given scenario."""
        if scenario == "mixed":
            return self._gen_mixed(n_ticks, start_price, tick_interval_ms)

        gen = getattr(self, f"_gen_{scenario}", None)
        if gen is None:
            raise ValueError(f"Unknown scenario: {scenario}. Choose from {self.SCENARIOS}")
        return gen(n_ticks, start_price, tick_interval_ms)

    def _noise(self, scale: float = 0.001) -> float:
        return self._rng.gauss(0, scale)

    def _gen_pump_dump(self, n: int, p0: float, dt: int) -> List[RawTick]:
        """Pump for 60%, dump for 40%."""
        ticks = []
        t0 = 1700000000000
        price = p0
        pump_end = int(n * 0.6)
        for i in range(n):
            if i < pump_end:
                drift = 0.0008 + self._noise(0.0003)
                vol_mult = 1.5
                obi = 0.3 + self._rng.random() * 0.4
            else:
                drift = -0.002 + self._noise(0.0005)
                vol_mult = 3.0
                obi = -0.3 - self._rng.random() * 0.5
            price *= (1 + drift)
            vol = self._rng.uniform(0.5, 5.0) * vol_mult
            ticks.append(RawTick(
                timestamp_ms=t0 + i * dt,
                price=price, volume=vol, obi=obi,
            ))
        return ticks

    def _gen_slow_bleed(self, n: int, p0: float, dt: int) -> List[RawTick]:
        ticks = []
        t0 = 1700000000000
        price = p0
        for i in range(n):
            drift = -0.0003 + self._noise(0.0005)
            price *= (1 + drift)
            vol = self._rng.uniform(1, 8)
            obi = -0.1 - self._rng.random() * 0.3
            ticks.append(RawTick(
                timestamp_ms=t0 + i * dt,
                price=price, volume=vol, obi=obi,
            ))
        return ticks

    def _gen_chop(self, n: int, p0: float, dt: int) -> List[RawTick]:
        ticks = []
        t0 = 1700000000000
        price = p0
        for i in range(n):
            drift = self._noise(0.001)
            price *= (1 + drift)
            vol = self._rng.uniform(0.3, 2.0)
            obi = self._noise(0.3)
            ticks.append(RawTick(
                timestamp_ms=t0 + i * dt,
                price=price, volume=vol, obi=obi,
            ))
        return ticks

    def _gen_ghost_rug(self, n: int, p0: float, dt: int) -> List[RawTick]:
        """Pump with ghost liquidity pulled at 50%."""
        ticks = []
        t0 = 1700000000000
        price = p0
        ghost_tick = int(n * 0.5)
        for i in range(n):
            if i < ghost_tick:
                drift = 0.0006 + self._noise(0.0003)
                obi = 0.2 + self._rng.random() * 0.3
                ghosts = []
            elif i == ghost_tick:
                drift = -0.001
                obi = -0.5
                ghosts = [{
                    "side": "bid", "notional_usd": 200_000,
                    "confidence": 0.85, "ts": t0 + i * dt,
                }]
            else:
                drift = -0.003 + self._noise(0.001)
                obi = -0.6 - self._rng.random() * 0.3
                ghosts = []
            price *= (1 + drift)
            vol = self._rng.uniform(1, 6)
            ticks.append(RawTick(
                timestamp_ms=t0 + i * dt,
                price=price, volume=vol, obi=obi,
                ghost_events=ghosts,
            ))
        return ticks

    def _gen_clean_pump(self, n: int, p0: float, dt: int) -> List[RawTick]:
        ticks = []
        t0 = 1700000000000
        price = p0
        for i in range(n):
            drift = 0.001 + self._noise(0.0003)
            price *= (1 + drift)
            vol = self._rng.uniform(1, 4)
            obi = 0.3 + self._rng.random() * 0.4
            ticks.append(RawTick(
                timestamp_ms=t0 + i * dt,
                price=price, volume=vol, obi=obi,
            ))
        return ticks

    def _gen_vpin_toxic(self, n: int, p0: float, dt: int) -> List[RawTick]:
        """VPIN slowly ramps to toxic then critical."""
        ticks = []
        t0 = 1700000000000
        price = p0
        for i in range(n):
            progress = i / max(n - 1, 1)
            if progress < 0.3:
                drift = 0.0003 + self._noise(0.0003)
                sell_ratio = 0.4
            elif progress < 0.7:
                drift = -0.0001 + self._noise(0.0004)
                sell_ratio = 0.65 + progress * 0.3
            else:
                drift = -0.001 + self._noise(0.0005)
                sell_ratio = 0.85
            price *= (1 + drift)
            total_vol = self._rng.uniform(5, 20)
            vol = total_vol * sell_ratio  # heavy sell volume
            obi = -0.2 - sell_ratio * 0.5
            ticks.append(RawTick(
                timestamp_ms=t0 + i * dt,
                price=price, volume=vol, obi=obi,
            ))
        return ticks

    def _gen_mixed(self, n: int, p0: float, dt: int) -> List[RawTick]:
        """Chain multiple scenarios together."""
        scenarios = ["clean_pump", "pump_dump", "chop", "slow_bleed", "vpin_toxic"]
        per = n // len(scenarios)
        ticks = []
        price = p0
        for sc in scenarios:
            gen = getattr(self, f"_gen_{sc}")
            chunk = gen(per, price, dt)
            ticks.extend(chunk)
            if chunk:
                price = chunk[-1].price
        return ticks


# ════════════════════════════════════════════════════
# DATA LOADERS
# ════════════════════════════════════════════════════

def load_ticks_csv(
    filepath: str,
    price_col: str = "price",
    volume_col: str = "volume",
    time_col: str = "timestamp_ms",
    obi_col: str = "obi",
) -> List[RawTick]:
    """Load tick data from CSV.
    
    Expected columns: timestamp_ms, price, volume, obi (optional)
    """
    ticks = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticks.append(RawTick(
                timestamp_ms=int(float(row.get(time_col, 0))),
                price=float(row[price_col]),
                volume=float(row.get(volume_col, 0)),
                obi=float(row.get(obi_col, 0)),
            ))
    return ticks


def load_ticks_json(filepath: str) -> List[RawTick]:
    """Load tick data from JSON (list of tick objects)."""
    with open(filepath, "r") as f:
        data = json.load(f)
    return [
        RawTick(
            timestamp_ms=t.get("timestamp_ms", t.get("ts", 0)),
            price=t["price"],
            volume=t.get("volume", 0),
            obi=t.get("obi", 0),
            ghost_events=t.get("ghost_events", []),
            macro_kill=t.get("macro_kill", False),
        )
        for t in data
    ]


# ════════════════════════════════════════════════════
# ENTRY STRATEGIES (pluggable)
# ════════════════════════════════════════════════════

class EntrySignal:
    """Base class for entry signal generators."""

    def should_enter(self, ticks: List[RawTick], idx: int) -> Optional[dict]:
        """Return entry params dict or None.
        
        Returns: {"side": "LONG"|"SHORT", "reason": str, ...} or None
        """
        raise NotImplementedError


class MomentumEntry(EntrySignal):
    """Enter LONG when price breaks N-tick high with volume confirmation."""

    def __init__(self, lookback: int = 20, volume_mult: float = 1.5):
        self.lookback = lookback
        self.volume_mult = volume_mult

    def should_enter(self, ticks: List[RawTick], idx: int) -> Optional[dict]:
        if idx < self.lookback:
            return None
        window = ticks[idx - self.lookback:idx]
        high = max(t.price for t in window)
        avg_vol = sum(t.volume for t in window) / max(len(window), 1)
        current = ticks[idx]

        if current.price > high and current.volume > avg_vol * self.volume_mult:
            return {"side": "LONG", "reason": f"momentum_break_{self.lookback}"}
        return None


class OBIReversalEntry(EntrySignal):
    """Enter on extreme OBI reversal — mean-reversion play."""

    def __init__(self, extreme_threshold: float = 0.7, lookback: int = 10):
        self.threshold = extreme_threshold
        self.lookback = lookback

    def should_enter(self, ticks: List[RawTick], idx: int) -> Optional[dict]:
        if idx < self.lookback + 1:
            return None
        window = ticks[idx - self.lookback:idx]
        avg_obi = sum(t.obi for t in window) / len(window)
        current = ticks[idx]

        if avg_obi < -self.threshold and current.obi > avg_obi + 0.3:
            return {"side": "LONG", "reason": "obi_reversal_long"}
        if avg_obi > self.threshold and current.obi < avg_obi - 0.3:
            return {"side": "SHORT", "reason": "obi_reversal_short"}
        return None


class FixedIntervalEntry(EntrySignal):
    """Enter at fixed intervals — useful for APM stress testing."""

    def __init__(self, every_n: int = 200, side: str = "LONG"):
        self.every_n = every_n
        self.side = side

    def should_enter(self, ticks: List[RawTick], idx: int) -> Optional[dict]:
        if idx > 0 and idx % self.every_n == 0:
            return {"side": self.side, "reason": f"fixed_interval_{self.every_n}"}
        return None


class MultiStrategyEntry(EntrySignal):
    """Combine multiple entry strategies (first match wins)."""

    def __init__(self, strategies: List[EntrySignal]):
        self.strategies = strategies

    def should_enter(self, ticks: List[RawTick], idx: int) -> Optional[dict]:
        for strat in self.strategies:
            signal = strat.should_enter(ticks, idx)
            if signal:
                return signal
        return None


# ════════════════════════════════════════════════════
# TRADE LOG
# ════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    """Complete record of one trade lifecycle."""
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    entry_tick_idx: int
    entry_ts: int
    exit_price: float = 0.0
    exit_tick_idx: int = 0
    exit_ts: int = 0
    exit_reason: str = ""
    pnl_pct: float = 0.0
    pnl_abs: float = 0.0
    quantity: float = 1.0
    ticks_held: int = 0
    duration_ms: int = 0
    max_favorable: float = 0.0  # max pnl during trade
    max_adverse: float = 0.0    # max drawdown during trade
    entry_signal: str = ""
    apm_params: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ════════════════════════════════════════════════════
# BACKTEST RESULTS & ANALYTICS
# ════════════════════════════════════════════════════

@dataclass
class BacktestResults:
    """Full analytics from a backtest run."""
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    equity_timestamps: List[int] = field(default_factory=list)
    total_ticks: int = 0
    wall_time_s: float = 0.0
    apm_params: Dict = field(default_factory=dict)
    strategy_name: str = ""
    symbol: str = ""

    # ── Computed analytics ──
    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winners(self) -> List[TradeRecord]:
        return [t for t in self.trades if t.pnl_pct > 0]

    @property
    def losers(self) -> List[TradeRecord]:
        return [t for t in self.trades if t.pnl_pct <= 0]

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self.winners) / len(self.trades)

    @property
    def total_pnl_pct(self) -> float:
        return sum(t.pnl_pct for t in self.trades)

    @property
    def avg_pnl_pct(self) -> float:
        if not self.trades:
            return 0.0
        return self.total_pnl_pct / len(self.trades)

    @property
    def avg_win_pct(self) -> float:
        if not self.winners:
            return 0.0
        return sum(t.pnl_pct for t in self.winners) / len(self.winners)

    @property
    def avg_loss_pct(self) -> float:
        if not self.losers:
            return 0.0
        return sum(t.pnl_pct for t in self.losers) / len(self.losers)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl_pct for t in self.winners)
        gross_loss = abs(sum(t.pnl_pct for t in self.losers))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def expectancy(self) -> float:
        """Kelly-style expectancy: (win_rate × avg_win) - (loss_rate × avg_loss)."""
        if not self.trades:
            return 0.0
        wr = self.win_rate
        return wr * self.avg_win_pct - (1 - wr) * abs(self.avg_loss_pct)

    @property
    def sharpe(self) -> float:
        """Sharpe ratio from per-trade returns (annualized approximation)."""
        if len(self.trades) < 2:
            return 0.0
        returns = [t.pnl_pct for t in self.trades]
        mean = statistics.mean(returns)
        std = statistics.stdev(returns)
        if std == 0:
            return 0.0
        # Assume ~100 trades/day → 36500 trades/year
        trades_per_year = 36500
        return (mean / std) * math.sqrt(trades_per_year)

    @property
    def max_drawdown_pct(self) -> float:
        """Max drawdown from equity curve."""
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    @property
    def exit_reason_breakdown(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for t in self.trades:
            counts[t.exit_reason] += 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    @property
    def avg_hold_ticks(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.ticks_held for t in self.trades) / len(self.trades)

    @property
    def avg_hold_duration_ms(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.duration_ms for t in self.trades) / len(self.trades)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            "=" * 60,
            f"  APEX CITADEL v3 — BACKTEST RESULTS",
            f"  Strategy: {self.strategy_name}",
            f"  Symbol: {self.symbol}",
            "=" * 60,
            f"  Total ticks:      {self.total_ticks:,}",
            f"  Wall time:        {self.wall_time_s:.2f}s",
            f"  Ticks/sec:        {self.total_ticks / max(self.wall_time_s, 0.001):,.0f}",
            "-" * 60,
            f"  Total trades:     {self.total_trades}",
            f"  Win rate:         {self.win_rate:.1%}",
            f"  Total PnL:        {self.total_pnl_pct:+.2f}%",
            f"  Avg PnL:          {self.avg_pnl_pct:+.4f}%",
            f"  Avg win:          {self.avg_win_pct:+.4f}%",
            f"  Avg loss:         {self.avg_loss_pct:+.4f}%",
            f"  Profit factor:    {self.profit_factor:.2f}",
            f"  Expectancy:       {self.expectancy:+.4f}%",
            f"  Sharpe (ann.):    {self.sharpe:.2f}",
            f"  Max drawdown:     {self.max_drawdown_pct:.2f}%",
            "-" * 60,
            f"  Avg hold ticks:   {self.avg_hold_ticks:.0f}",
            f"  Avg hold time:    {self.avg_hold_duration_ms / 1000:.1f}s",
            "-" * 60,
            "  EXIT REASONS:",
        ]
        for reason, count in self.exit_reason_breakdown.items():
            pct = count / max(self.total_trades, 1) * 100
            lines.append(f"    {reason:20s}  {count:4d}  ({pct:.1f}%)")
        lines.append("=" * 60)
        return "\n".join(lines)

    def export_json(self, filepath: str):
        """Export results to JSON."""
        data = {
            "summary": {
                "total_trades": self.total_trades,
                "win_rate": self.win_rate,
                "total_pnl_pct": self.total_pnl_pct,
                "avg_pnl_pct": self.avg_pnl_pct,
                "profit_factor": self.profit_factor,
                "expectancy": self.expectancy,
                "sharpe": self.sharpe,
                "max_drawdown_pct": self.max_drawdown_pct,
                "exit_reasons": self.exit_reason_breakdown,
                "total_ticks": self.total_ticks,
                "wall_time_s": self.wall_time_s,
                "strategy": self.strategy_name,
                "symbol": self.symbol,
            },
            "trades": [t.to_dict() for t in self.trades],
            "equity_curve": self.equity_curve,
            "apm_params": self.apm_params,
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def export_csv(self, filepath: str):
        """Export trade log to CSV."""
        if not self.trades:
            return
        fields = list(self.trades[0].to_dict().keys())
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for t in self.trades:
                writer.writerow(t.to_dict())


# ════════════════════════════════════════════════════
# BACKTEST ENGINE
# ════════════════════════════════════════════════════

@dataclass
class APMConfig:
    """Tunable APM parameters for backtesting."""
    take_profit_pct: float = 5.0
    hard_stop_pct: float = 3.0
    alpha_decay_s: float = ALPHA_DECAY_S
    alpha_min_move_pct: float = ALPHA_MIN_MOVE_PCT
    time_limit_s: float = 1800.0
    vpin_bucket_vol: float = 0.0
    ghost_min_notional: float = 50_000.0
    atr_default: float = 0.02  # 2% ATR default for backtesting

    def to_dict(self) -> dict:
        return asdict(self)


class BacktestEngine:
    """Tick-level backtester that replays data through the real APM.
    
    The engine:
    1. Steps through ticks sequentially
    2. Checks entry strategy at each tick
    3. Routes active positions through APM.process_tick()
    4. Tracks full trade lifecycle + equity curve
    5. Supports concurrent positions
    """

    def __init__(
        self,
        apm_config: Optional[APMConfig] = None,
        max_concurrent: int = 1,
        initial_equity: float = 10_000.0,
        position_size_pct: float = 100.0,   # % of equity per trade
        fee_pct: float = 0.04,              # 4bps per side (Binance taker)
        slippage_pct: float = 0.01,         # 1bp slippage per side
    ):
        self.config = apm_config or APMConfig()
        self.max_concurrent = max_concurrent
        self.initial_equity = initial_equity
        self.position_size_pct = position_size_pct
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct

        self._ticks: List[RawTick] = []
        self._strategy: Optional[EntrySignal] = None
        self._symbol: str = "UNKNOWN"

    def load_ticks(self, source, **kwargs):
        """Load ticks from file path, list, or generator.
        
        Args:
            source: filepath (str), list of RawTick, or list of dicts
        """
        if isinstance(source, str):
            if source.endswith(".json"):
                self._ticks = load_ticks_json(source)
            else:
                self._ticks = load_ticks_csv(source, **kwargs)
        elif isinstance(source, list):
            if source and isinstance(source[0], RawTick):
                self._ticks = source
            elif source and isinstance(source[0], dict):
                self._ticks = [
                    RawTick(
                        timestamp_ms=t.get("timestamp_ms", 0),
                        price=t["price"],
                        volume=t.get("volume", 0),
                        obi=t.get("obi", 0),
                    )
                    for t in source
                ]
            else:
                self._ticks = source
        log.info(f"[BT] Loaded {len(self._ticks)} ticks")

    def set_strategy(self, strategy: EntrySignal):
        self._strategy = strategy

    def set_symbol(self, symbol: str):
        self._symbol = symbol

    def _estimate_atr(self, ticks: List[RawTick], idx: int, lookback: int = 50) -> float:
        """Estimate ATR from recent ticks."""
        start = max(0, idx - lookback)
        window = ticks[start:idx + 1]
        if len(window) < 2:
            return self.config.atr_default
        prices = [t.price for t in window]
        high = max(prices)
        low = min(prices)
        mid = (high + low) / 2
        if mid == 0:
            return self.config.atr_default
        return (high - low) / mid

    async def run(self) -> BacktestResults:
        """Execute the backtest. Returns full analytics."""
        if not self._ticks:
            raise ValueError("No ticks loaded. Call load_ticks() first.")
        if not self._strategy:
            raise ValueError("No strategy set. Call set_strategy() first.")

        apm = ActivePositionManager()
        results = BacktestResults(
            apm_params=self.config.to_dict(),
            strategy_name=type(self._strategy).__name__,
            symbol=self._symbol,
        )

        equity = self.initial_equity
        results.equity_curve.append(equity)
        results.equity_timestamps.append(
            self._ticks[0].timestamp_ms if self._ticks else 0
        )

        # Track active trades
        active: Dict[str, dict] = {}  # pos_id -> {trade_record, max_fav, max_adv}
        all_trades: List[TradeRecord] = []

        # Simulated time for APM (use tick timestamps converted to monotonic-like)
        base_mono = time.monotonic()
        tick_base_ts = self._ticks[0].timestamp_ms if self._ticks else 0

        start_wall = time.monotonic()

        for idx, raw_tick in enumerate(self._ticks):
            tick = raw_tick.to_tick_data()

            # Fake monotonic time from tick timestamps for APM internals
            # We patch time for alpha decay etc. via tick count instead
            sim_elapsed_s = (raw_tick.timestamp_ms - tick_base_ts) / 1000.0

            # ─── Process active positions ───
            closed_this_tick = []
            for pos_id, info in active.items():
                decision = await apm.process_tick(pos_id, tick)

                # Track max favorable / adverse
                tr = info["record"]
                if tr.side == "LONG":
                    unrealized = (raw_tick.price - tr.entry_price) / tr.entry_price * 100
                else:
                    unrealized = (tr.entry_price - raw_tick.price) / tr.entry_price * 100
                info["max_fav"] = max(info["max_fav"], unrealized)
                info["max_adv"] = min(info["max_adv"], unrealized)

                if decision.action == "EXIT":
                    tr.exit_price = raw_tick.price
                    tr.exit_tick_idx = idx
                    tr.exit_ts = raw_tick.timestamp_ms
                    tr.exit_reason = decision.reason.value if decision.reason else "unknown"
                    tr.ticks_held = idx - tr.entry_tick_idx

                    # Calculate PnL with fees + slippage
                    if tr.side == "LONG":
                        raw_pnl = (tr.exit_price - tr.entry_price) / tr.entry_price * 100
                    else:
                        raw_pnl = (tr.entry_price - tr.exit_price) / tr.entry_price * 100

                    total_cost = 2 * (self.fee_pct + self.slippage_pct)
                    tr.pnl_pct = raw_pnl - total_cost
                    tr.pnl_abs = equity * (self.position_size_pct / 100) * (tr.pnl_pct / 100)
                    tr.duration_ms = tr.exit_ts - tr.entry_ts
                    tr.max_favorable = info["max_fav"]
                    tr.max_adverse = info["max_adv"]

                    equity += tr.pnl_abs
                    all_trades.append(tr)
                    closed_this_tick.append(pos_id)

            for pos_id in closed_this_tick:
                del active[pos_id]

            # ─── Check for new entries ───
            if len(active) < self.max_concurrent:
                signal = self._strategy.should_enter(self._ticks, idx)
                if signal:
                    atr = self._estimate_atr(self._ticks, idx)
                    pos_id = await apm.register_position(
                        symbol=self._symbol,
                        side=signal["side"],
                        entry_price=raw_tick.price,
                        quantity=1.0,
                        atr=raw_tick.price * atr,
                        take_profit_pct=self.config.take_profit_pct,
                        hard_stop_pct=self.config.hard_stop_pct,
                        alpha_decay_s=self.config.alpha_decay_s,
                        alpha_min_move_pct=self.config.alpha_min_move_pct,
                        time_limit_s=self.config.time_limit_s,
                        vpin_bucket_vol=self.config.vpin_bucket_vol,
                        ghost_min_notional=self.config.ghost_min_notional,
                    )

                    record = TradeRecord(
                        trade_id=pos_id,
                        symbol=self._symbol,
                        side=signal["side"],
                        entry_price=raw_tick.price,
                        entry_tick_idx=idx,
                        entry_ts=raw_tick.timestamp_ms,
                        entry_signal=signal.get("reason", "unknown"),
                        apm_params=self.config.to_dict(),
                    )
                    active[pos_id] = {
                        "record": record,
                        "max_fav": 0.0,
                        "max_adv": 0.0,
                    }

            # ─── Equity snapshot ───
            if idx % 100 == 0 or idx == len(self._ticks) - 1:
                results.equity_curve.append(equity)
                results.equity_timestamps.append(raw_tick.timestamp_ms)

        # ─── Force-close remaining positions ───
        final_price = self._ticks[-1].price if self._ticks else 0
        for pos_id, info in active.items():
            tr = info["record"]
            tr.exit_price = final_price
            tr.exit_tick_idx = len(self._ticks) - 1
            tr.exit_ts = self._ticks[-1].timestamp_ms if self._ticks else 0
            tr.exit_reason = "forced_close_eod"
            tr.ticks_held = tr.exit_tick_idx - tr.entry_tick_idx
            if tr.side == "LONG":
                raw_pnl = (tr.exit_price - tr.entry_price) / tr.entry_price * 100
            else:
                raw_pnl = (tr.entry_price - tr.exit_price) / tr.entry_price * 100
            total_cost = 2 * (self.fee_pct + self.slippage_pct)
            tr.pnl_pct = raw_pnl - total_cost
            tr.pnl_abs = equity * (self.position_size_pct / 100) * (tr.pnl_pct / 100)
            tr.duration_ms = tr.exit_ts - tr.entry_ts
            tr.max_favorable = info["max_fav"]
            tr.max_adverse = info["max_adv"]
            equity += tr.pnl_abs
            all_trades.append(tr)
            await apm.force_exit(pos_id, final_price)

        results.trades = all_trades
        results.total_ticks = len(self._ticks)
        results.wall_time_s = time.monotonic() - start_wall
        results.equity_curve.append(equity)

        return results


# ════════════════════════════════════════════════════
# PARAMETER SWEEP / GRID SEARCH
# ════════════════════════════════════════════════════

@dataclass
class SweepResult:
    """One row from a parameter sweep."""
    params: Dict
    total_pnl: float
    win_rate: float
    sharpe: float
    max_dd: float
    total_trades: int
    profit_factor: float
    expectancy: float


class ParameterSweep:
    """Grid search over APM parameters to find optimal settings.
    
    Usage:
        sweep = ParameterSweep(ticks, strategy)
        sweep.add_param("take_profit_pct", [2.0, 3.0, 5.0, 8.0])
        sweep.add_param("hard_stop_pct", [1.0, 2.0, 3.0])
        sweep.add_param("alpha_decay_s", [120, 180, 300])
        results = await sweep.run()
        sweep.print_top(10)
    """

    def __init__(
        self,
        ticks: List[RawTick],
        strategy: EntrySignal,
        symbol: str = "SWEEP/USDT",
        base_config: Optional[APMConfig] = None,
        **engine_kwargs,
    ):
        self._ticks = ticks
        self._strategy = strategy
        self._symbol = symbol
        self._base = base_config or APMConfig()
        self._engine_kwargs = engine_kwargs
        self._params: Dict[str, List] = {}
        self._results: List[SweepResult] = []

    def add_param(self, name: str, values: List):
        """Add a parameter dimension to sweep."""
        if not hasattr(self._base, name):
            raise ValueError(f"APMConfig has no param '{name}'")
        self._params[name] = values

    def _generate_combos(self) -> List[Dict]:
        """Generate all parameter combinations."""
        if not self._params:
            return [{}]
        keys = list(self._params.keys())
        combos = [{}]
        for key in keys:
            new_combos = []
            for combo in combos:
                for val in self._params[key]:
                    c = dict(combo)
                    c[key] = val
                    new_combos.append(c)
            combos = new_combos
        return combos

    async def run(self, verbose: bool = True) -> List[SweepResult]:
        """Execute all parameter combinations."""
        combos = self._generate_combos()
        total = len(combos)
        if verbose:
            log.info(f"[SWEEP] Running {total} parameter combinations")

        self._results = []
        for i, combo in enumerate(combos):
            cfg = APMConfig(**{**asdict(self._base), **combo})
            engine = BacktestEngine(apm_config=cfg, **self._engine_kwargs)
            engine.load_ticks(self._ticks)
            engine.set_strategy(self._strategy)
            engine.set_symbol(self._symbol)

            result = await engine.run()
            sr = SweepResult(
                params=combo,
                total_pnl=result.total_pnl_pct,
                win_rate=result.win_rate,
                sharpe=result.sharpe,
                max_dd=result.max_drawdown_pct,
                total_trades=result.total_trades,
                profit_factor=result.profit_factor,
                expectancy=result.expectancy,
            )
            self._results.append(sr)

            if verbose and (i + 1) % max(1, total // 10) == 0:
                log.info(f"[SWEEP] {i + 1}/{total} complete")

        # Sort by Sharpe
        self._results.sort(key=lambda r: r.sharpe, reverse=True)
        return self._results

    def print_top(self, n: int = 10) -> str:
        """Print top N results."""
        lines = [
            "=" * 90,
            "  PARAMETER SWEEP — TOP RESULTS (sorted by Sharpe)",
            "=" * 90,
            f"  {'#':>3}  {'Sharpe':>7}  {'PnL%':>8}  {'WinR':>6}  {'PF':>6}  {'MaxDD':>7}  {'Trades':>6}  Params",
            "-" * 90,
        ]
        for i, r in enumerate(self._results[:n]):
            param_str = ", ".join(f"{k}={v}" for k, v in r.params.items())
            lines.append(
                f"  {i + 1:3d}  {r.sharpe:7.2f}  {r.total_pnl:+8.2f}  "
                f"{r.win_rate:5.1%}  {r.profit_factor:6.2f}  {r.max_dd:6.2f}%  "
                f"{r.total_trades:6d}  {param_str}"
            )
        lines.append("=" * 90)
        text = "\n".join(lines)
        print(text)
        return text

    def export_json(self, filepath: str):
        """Export sweep results."""
        data = [
            {
                "rank": i + 1,
                "params": r.params,
                "sharpe": r.sharpe,
                "total_pnl": r.total_pnl,
                "win_rate": r.win_rate,
                "profit_factor": r.profit_factor,
                "max_drawdown": r.max_dd,
                "total_trades": r.total_trades,
                "expectancy": r.expectancy,
            }
            for i, r in enumerate(self._results)
        ]
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)


# ════════════════════════════════════════════════════
# QUICK-RUN CLI
# ════════════════════════════════════════════════════

async def quick_run(
    scenario: str = "pump_dump",
    n_ticks: int = 2000,
    strategy: str = "momentum",
    verbose: bool = True,
) -> BacktestResults:
    """One-liner backtest with synthetic data.
    
    Example:
        results = await quick_run("pump_dump", 3000)
    """
    gen = SyntheticTickGenerator(seed=42)
    ticks = gen.generate(scenario=scenario, n_ticks=n_ticks)

    strat: EntrySignal
    if strategy == "momentum":
        strat = MomentumEntry(lookback=20, volume_mult=1.3)
    elif strategy == "obi":
        strat = OBIReversalEntry()
    elif strategy == "fixed":
        strat = FixedIntervalEntry(every_n=200)
    else:
        strat = MomentumEntry()

    engine = BacktestEngine(
        apm_config=APMConfig(),
        max_concurrent=1,
        initial_equity=10_000.0,
    )
    engine.load_ticks(ticks)
    engine.set_strategy(strat)
    engine.set_symbol(f"SYN_{scenario.upper()}/USDT")

    results = await engine.run()
    if verbose:
        print(results.summary())
    return results


async def quick_sweep(
    scenario: str = "mixed",
    n_ticks: int = 3000,
) -> List[SweepResult]:
    """One-liner parameter sweep with synthetic data."""
    gen = SyntheticTickGenerator(seed=42)
    ticks = gen.generate(scenario=scenario, n_ticks=n_ticks)
    strat = FixedIntervalEntry(every_n=150)

    sweep = ParameterSweep(ticks, strat)
    sweep.add_param("take_profit_pct", [2.0, 3.0, 5.0])
    sweep.add_param("hard_stop_pct", [1.5, 2.0, 3.0])
    sweep.add_param("alpha_decay_s", [120, 180, 300])

    results = await sweep.run()
    sweep.print_top(10)
    return results


if __name__ == "__main__":
    asyncio.run(quick_run("mixed", 3000))
