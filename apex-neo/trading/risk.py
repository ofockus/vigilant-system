"""
Robin Hood Risk Manager.

Hard capital protection with drawdown monitoring, auto-pause,
and equity floor enforcement. Prevents catastrophic losses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class RiskState:
    starting_equity: float = 0.0
    current_equity: float = 0.0
    peak_equity: float = 0.0
    drawdown_pct: float = 0.0
    paused: bool = False
    pause_until: float = 0.0
    pause_reason: str = ""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    equity_history: list[tuple[float, float]] = field(default_factory=list)


class RiskManager:
    """Robin Hood risk: max drawdown, pause, equity floor."""

    def __init__(
        self,
        capital: float,
        max_drawdown_pct: float = 4.0,
        pause_duration_s: int = 1800,
        equity_floor_pct: float = 50.0,
    ) -> None:
        self.max_drawdown_pct = max_drawdown_pct
        self.pause_duration_s = pause_duration_s
        self.equity_floor_pct = equity_floor_pct

        self.state = RiskState(
            starting_equity=capital,
            current_equity=capital,
            peak_equity=capital,
        )
        logger.info(
            "Risk manager | capital={} maxDD={}% pause={}s floor={}%",
            capital, max_drawdown_pct, pause_duration_s, equity_floor_pct,
        )

    def update_equity(self, pnl: float) -> None:
        """Update equity after a trade result."""
        self.state.current_equity += pnl
        self.state.peak_equity = max(self.state.peak_equity, self.state.current_equity)

        # Record equity point
        self.state.equity_history.append((time.time(), self.state.current_equity))
        # Keep last 5000 points
        if len(self.state.equity_history) > 5000:
            self.state.equity_history = self.state.equity_history[-5000:]

        # Calculate drawdown from peak
        if self.state.peak_equity > 0:
            self.state.drawdown_pct = (
                (self.state.peak_equity - self.state.current_equity)
                / self.state.peak_equity
                * 100
            )

        if pnl > 0:
            self.state.winning_trades += 1
        else:
            self.state.losing_trades += 1
        self.state.total_trades += 1

    def check_allowed(self) -> tuple[bool, str]:
        """Check if trading is currently allowed. Returns (allowed, reason)."""
        now = time.time()

        # Check pause timer
        if self.state.paused:
            if now >= self.state.pause_until:
                self.state.paused = False
                self.state.pause_reason = ""
                logger.info("Risk pause expired, trading resumed")
            else:
                remaining = self.state.pause_until - now
                return False, f"Paused: {self.state.pause_reason} ({remaining:.0f}s remaining)"

        # Check drawdown
        if self.state.drawdown_pct >= self.max_drawdown_pct:
            self._pause(f"Max drawdown {self.state.drawdown_pct:.2f}% >= {self.max_drawdown_pct}%")
            return False, self.state.pause_reason

        # Check equity floor
        floor = self.state.starting_equity * self.equity_floor_pct / 100
        if self.state.current_equity < floor:
            self._pause(f"Equity {self.state.current_equity:.2f} below floor {floor:.2f}")
            return False, self.state.pause_reason

        return True, "OK"

    def _pause(self, reason: str) -> None:
        self.state.paused = True
        self.state.pause_until = time.time() + self.pause_duration_s
        self.state.pause_reason = reason
        logger.warning("RISK PAUSE | {} | resuming in {}s", reason, self.pause_duration_s)

    def get_status(self) -> dict[str, Any]:
        allowed, reason = self.check_allowed()
        return {
            "starting_equity": self.state.starting_equity,
            "current_equity": self.state.current_equity,
            "peak_equity": self.state.peak_equity,
            "drawdown_pct": self.state.drawdown_pct,
            "paused": self.state.paused,
            "pause_reason": self.state.pause_reason,
            "allowed": allowed,
            "reason": reason,
            "total_trades": self.state.total_trades,
            "win_rate": (
                self.state.winning_trades / self.state.total_trades * 100
                if self.state.total_trades > 0
                else 0.0
            ),
        }

    def get_equity_curve(self) -> list[dict[str, float]]:
        return [
            {"t": t, "equity": eq}
            for t, eq in self.state.equity_history
        ]
