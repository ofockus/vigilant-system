"""
Risk manager for $200 micro-capital.

Dynamic position sizing via ATR + account risk percentage.
Dynamic leverage (5x-15x) based on volatility.
Daily loss limit (4%), max drawdown (12%), consecutive loss pause.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class RiskState:
    starting_equity: float = 200.0
    current_equity: float = 200.0
    peak_equity: float = 200.0
    daily_start_equity: float = 200.0
    daily_pnl: float = 0.0
    drawdown_pct: float = 0.0
    consecutive_losses: int = 0
    total_trades: int = 0
    total_wins: int = 0
    paused: bool = False
    pause_until: float = 0.0
    pause_reason: str = ""
    shutdown: bool = False
    day_start_ts: float = 0.0
    equity_curve: list[tuple[float, float]] = field(default_factory=list)


class RiskManager:
    """Account-level risk management."""

    def __init__(
        self,
        capital: float = 200.0,
        max_risk_pct: float = 0.75,
        leverage_min: int = 5,
        leverage_max: int = 15,
        leverage_dynamic: bool = True,
        daily_loss_pct: float = 4.0,
        max_drawdown_pct: float = 12.0,
        max_concurrent: int = 3,
        pause_after_losses: int = 4,
        pause_duration_s: int = 600,
    ) -> None:
        self.max_risk_pct = max_risk_pct
        self.leverage_min = leverage_min
        self.leverage_max = leverage_max
        self.leverage_dynamic = leverage_dynamic
        self.daily_loss_pct = daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_concurrent = max_concurrent
        self.pause_after_losses = pause_after_losses
        self.pause_duration_s = pause_duration_s

        self.state = RiskState(
            starting_equity=capital,
            current_equity=capital,
            peak_equity=capital,
            daily_start_equity=capital,
            day_start_ts=time.time(),
        )
        self.open_positions: int = 0

    def compute_leverage(self, micro_vol: float) -> int:
        """Dynamic leverage based on current volatility."""
        if not self.leverage_dynamic:
            return self.leverage_min

        # High vol → lower leverage, low vol → higher leverage
        if micro_vol <= 0:
            return self.leverage_max

        # Inverse relationship: vol 0.001 → 15x, vol 0.01 → 5x
        target = int(0.015 / (micro_vol + 0.001))
        return max(self.leverage_min, min(self.leverage_max, target))

    def compute_position_size(self, price: float, atr_pct: float,
                               leverage: int) -> float:
        """Position size in base currency.

        Risk = max_risk_pct of equity. Size = risk_amount / (SL_distance * leverage).
        """
        risk_amount = self.state.current_equity * self.max_risk_pct / 100
        sl_pct = max(atr_pct * 1.5, 0.09)  # at least 0.09%
        sl_distance = price * sl_pct / 100

        if sl_distance <= 0:
            return 0.0

        # Notional size
        notional = risk_amount / (sl_pct / 100) * leverage
        # Cap at 90% of equity * leverage
        max_notional = self.state.current_equity * leverage * 0.9
        notional = min(notional, max_notional)

        qty = notional / price
        return qty

    def record_trade(self, pnl_usd: float) -> None:
        """Record a completed trade."""
        self.state.total_trades += 1
        self.state.current_equity += pnl_usd
        self.state.daily_pnl += pnl_usd

        if pnl_usd > 0:
            self.state.total_wins += 1
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1

        self.state.peak_equity = max(self.state.peak_equity, self.state.current_equity)
        self.state.equity_curve.append((time.time(), self.state.current_equity))

        # Keep last 10k points
        if len(self.state.equity_curve) > 10000:
            self.state.equity_curve = self.state.equity_curve[-10000:]

    def check_allowed(self) -> tuple[bool, str]:
        """Check if new trades are allowed."""
        now = time.time()

        # Check shutdown (max drawdown)
        if self.state.shutdown:
            return False, "SHUTDOWN: max drawdown exceeded"

        # Check daily reset
        if now - self.state.day_start_ts > 86400:
            self.state.daily_pnl = 0.0
            self.state.daily_start_equity = self.state.current_equity
            self.state.day_start_ts = now

        # Check pause timer
        if self.state.paused:
            if now >= self.state.pause_until:
                self.state.paused = False
                self.state.pause_reason = ""
                logger.info("Risk pause expired")
            else:
                remaining = self.state.pause_until - now
                return False, f"PAUSED: {self.state.pause_reason} ({remaining:.0f}s)"

        # Max drawdown → permanent shutdown
        dd = (self.state.peak_equity - self.state.current_equity) / self.state.peak_equity * 100
        self.state.drawdown_pct = dd
        if dd >= self.max_drawdown_pct:
            self.state.shutdown = True
            logger.critical("MAX DRAWDOWN {:.1f}% — SHUTDOWN", dd)
            return False, f"SHUTDOWN: drawdown {dd:.1f}% >= {self.max_drawdown_pct}%"

        # Daily loss limit → pause 24h
        daily_loss_pct = -self.state.daily_pnl / self.state.daily_start_equity * 100
        if daily_loss_pct >= self.daily_loss_pct:
            self._pause(f"Daily loss {daily_loss_pct:.1f}% >= {self.daily_loss_pct}%", 86400)
            return False, self.state.pause_reason

        # Consecutive losses → short pause
        if self.state.consecutive_losses >= self.pause_after_losses:
            self._pause(
                f"{self.state.consecutive_losses} consecutive losses",
                self.pause_duration_s,
            )
            self.state.consecutive_losses = 0
            return False, self.state.pause_reason

        # Max concurrent positions
        if self.open_positions >= self.max_concurrent:
            return False, f"MAX_CONCURRENT: {self.open_positions}/{self.max_concurrent}"

        return True, "OK"

    def _pause(self, reason: str, duration_s: int) -> None:
        self.state.paused = True
        self.state.pause_until = time.time() + duration_s
        self.state.pause_reason = reason
        logger.warning("RISK PAUSE: {} | {}s", reason, duration_s)

    def get_status(self) -> dict[str, Any]:
        ok, reason = self.check_allowed()
        return {
            "equity": round(self.state.current_equity, 4),
            "peak": round(self.state.peak_equity, 4),
            "drawdown_pct": round(self.state.drawdown_pct, 2),
            "daily_pnl": round(self.state.daily_pnl, 4),
            "trades": self.state.total_trades,
            "wins": self.state.total_wins,
            "win_rate": round(self.state.total_wins / max(self.state.total_trades, 1) * 100, 1),
            "consecutive_losses": self.state.consecutive_losses,
            "allowed": ok,
            "reason": reason,
        }
