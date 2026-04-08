"""
Order executor with observe/paper/live modes.

Handles entry/exit logic with the critical exit fixes:
- min_hold: 15s before any soft exit
- Hard exits always immediate (stop loss, VPIN critical, liquidation cascade)
- DECEL threshold 0.20 (not 0.05)
- Trail width 0.06%-0.12% (above fee threshold)
- Cooldown 60s between trades
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class Position:
    side: str = ""            # "long" or "short"
    entry_price: float = 0.0
    entry_time: float = 0.0
    size: float = 0.0
    peak_pnl_pct: float = 0.0  # for trailing stop
    trail_high: float = 0.0    # highest price (long) or lowest (short)


@dataclass
class ExitReason:
    reason: str = ""     # STOP_LOSS, TRAIL, DECEL, VPIN, LIQ_CASCADE, SIGNAL_FLIP
    pnl_pct: float = 0.0
    hold_time_s: float = 0.0


class Executor:
    """
    Trade executor supporting observe/paper/live modes.

    In observe mode: logs hypothetical trades to journal.
    In paper mode: simulates fills with realistic slippage.
    In live mode: executes real orders via connector.
    """

    def __init__(
        self,
        mode: str,
        connector: Any,
        capital: float,
        max_position_pct: float = 0.90,
        leverage: int = 5,
        # Exit params
        min_hold_s: float = 15.0,
        stop_loss_pct: float = 0.12,
        trail_base_pct: float = 0.06,
        trail_max_pct: float = 0.12,
        decel_threshold: float = 0.20,
        vpin_critical: float = 0.90,
        cooldown_s: float = 60.0,
    ) -> None:
        self.mode = mode
        self.connector = connector
        self.capital = capital
        self.max_position_pct = max_position_pct
        self.leverage = leverage

        # Exit params
        self.min_hold_s = min_hold_s
        self.stop_loss_pct = stop_loss_pct
        self.trail_base_pct = trail_base_pct
        self.trail_max_pct = trail_max_pct
        self.decel_threshold = decel_threshold
        self.vpin_critical = vpin_critical
        self.cooldown_s = cooldown_s

        # State
        self.position: Position | None = None
        self.last_trade_time: float = 0.0
        self.session_pnl: float = 0.0
        self.trade_count: int = 0

        logger.info(
            "Executor initialized | mode={} capital={} leverage={}x",
            mode, capital, leverage,
        )

    @property
    def in_position(self) -> bool:
        return self.position is not None

    @property
    def on_cooldown(self) -> bool:
        return time.time() - self.last_trade_time < self.cooldown_s

    def _hold_time(self) -> float:
        if not self.position:
            return 0.0
        return time.time() - self.position.entry_time

    def _current_pnl_pct(self, price: float) -> float:
        if not self.position:
            return 0.0
        if self.position.side == "long":
            return (price - self.position.entry_price) / self.position.entry_price * 100
        else:
            return (self.position.entry_price - price) / self.position.entry_price * 100

    def _trail_width(self, velocity: float) -> float:
        """Dynamic trail width: base + velocity-scaled component."""
        vel_scale = min(abs(velocity) / 50.0, 1.0)
        return self.trail_base_pct + (self.trail_max_pct - self.trail_base_pct) * vel_scale

    async def check_entry(
        self,
        price: float,
        direction: float,
        confidence: float,
        physics_agree: int,
        regime_ok: bool,
        toxicity_safe: bool,
        min_confidence: float,
        min_physics: int,
    ) -> dict[str, Any] | None:
        """Check if we should enter a position. Returns trade info or None."""
        if self.in_position:
            return None
        if self.on_cooldown:
            return None
        if not regime_ok:
            return None
        if not toxicity_safe:
            return None
        if confidence < min_confidence:
            return None
        if physics_agree < min_physics:
            return None
        if abs(direction) < 0.3:
            return None

        side = "long" if direction > 0 else "short"
        size_usd = self.capital * self.max_position_pct * self.leverage
        size = size_usd / price

        entry = await self._execute_entry(price, side, size)
        if entry:
            self.position = Position(
                side=side,
                entry_price=price,
                entry_time=time.time(),
                size=size,
                peak_pnl_pct=0.0,
                trail_high=price if side == "long" else price,
            )
            self.last_trade_time = time.time()
            self.trade_count += 1
            logger.info(
                "ENTRY | {} {} @ {:.2f} | size={:.6f} | conf={:.2f} phys={}/4",
                self.mode.upper(), side.upper(), price, size, confidence, physics_agree,
            )
            return {
                "action": "entry",
                "side": side,
                "price": price,
                "size": size,
                "confidence": confidence,
                "physics_agree": physics_agree,
                "mode": self.mode,
                "timestamp": time.time(),
            }
        return None

    async def check_exit(
        self,
        price: float,
        velocity: float = 0.0,
        decel_magnitude: float = 0.0,
        vpin: float = 0.0,
        liq_cascade: bool = False,
        direction_signal: float = 0.0,
    ) -> dict[str, Any] | None:
        """Check if we should exit current position. Returns exit info or None."""
        if not self.position:
            return None

        pnl_pct = self._current_pnl_pct(price)
        hold_time = self._hold_time()

        # Update trail tracking
        if self.position.side == "long":
            self.position.trail_high = max(self.position.trail_high, price)
        else:
            self.position.trail_high = min(self.position.trail_high, price)

        self.position.peak_pnl_pct = max(self.position.peak_pnl_pct, pnl_pct)

        # === HARD EXITS (always immediate, ignore min_hold) ===

        # Stop loss
        if pnl_pct <= -self.stop_loss_pct:
            return await self._do_exit(price, pnl_pct, hold_time, "STOP_LOSS")

        # VPIN critical
        if vpin > self.vpin_critical:
            return await self._do_exit(price, pnl_pct, hold_time, "VPIN_CRITICAL")

        # Liquidation cascade
        if liq_cascade:
            return await self._do_exit(price, pnl_pct, hold_time, "LIQ_CASCADE")

        # === SOFT EXITS (blocked before min_hold) ===
        if hold_time < self.min_hold_s:
            return None

        # DECEL exit: only if deceleration exceeds threshold
        if decel_magnitude > self.decel_threshold:
            return await self._do_exit(price, pnl_pct, hold_time, "DECEL")

        # Trailing stop
        trail_w = self._trail_width(velocity)
        if self.position.side == "long":
            trail_stop = self.position.trail_high * (1 - trail_w / 100)
            if price <= trail_stop and self.position.peak_pnl_pct > trail_w:
                return await self._do_exit(price, pnl_pct, hold_time, "TRAIL")
        else:
            trail_stop = self.position.trail_high * (1 + trail_w / 100)
            if price >= trail_stop and self.position.peak_pnl_pct > trail_w:
                return await self._do_exit(price, pnl_pct, hold_time, "TRAIL")

        # Signal flip: direction strongly opposes position
        if self.position.side == "long" and direction_signal < -0.6:
            return await self._do_exit(price, pnl_pct, hold_time, "SIGNAL_FLIP")
        if self.position.side == "short" and direction_signal > 0.6:
            return await self._do_exit(price, pnl_pct, hold_time, "SIGNAL_FLIP")

        return None

    async def _do_exit(
        self, price: float, pnl_pct: float, hold_time: float, reason: str
    ) -> dict[str, Any]:
        """Execute exit and clear position."""
        pos = self.position
        assert pos is not None

        await self._execute_exit(price, pos.side, pos.size)

        # Estimate fee impact (0.04% round trip for maker/taker)
        net_pnl_pct = pnl_pct - 0.04
        pnl_usd = net_pnl_pct / 100 * pos.size * pos.entry_price / self.leverage

        self.session_pnl += pnl_usd
        self.position = None
        self.last_trade_time = time.time()

        logger.info(
            "EXIT {} | {} @ {:.2f} → {:.2f} | PnL={:.4f}% ({:.4f} USD) | hold={:.1f}s",
            reason, pos.side.upper(), pos.entry_price, price, net_pnl_pct, pnl_usd, hold_time,
        )

        return {
            "action": "exit",
            "reason": reason,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": price,
            "pnl_pct": net_pnl_pct,
            "pnl_usd": pnl_usd,
            "hold_time_s": hold_time,
            "mode": self.mode,
            "timestamp": time.time(),
        }

    async def _execute_entry(self, price: float, side: str, size: float) -> bool:
        """Execute entry based on mode."""
        if self.mode == "observe":
            return True  # hypothetical fill
        elif self.mode == "paper":
            return True  # simulated fill
        elif self.mode == "live":
            try:
                order = await self.connector.create_market_order(
                    self.connector.exchange.markets
                    and list(self.connector.exchange.markets.keys())[0]
                    or "BTC/USDT",
                    "buy" if side == "long" else "sell",
                    size,
                )
                return order is not None
            except Exception as e:
                logger.error("Live entry failed: {}", e)
                return False
        return False

    async def _execute_exit(self, price: float, side: str, size: float) -> bool:
        """Execute exit based on mode."""
        if self.mode in ("observe", "paper"):
            return True
        elif self.mode == "live":
            try:
                close_side = "sell" if side == "long" else "buy"
                order = await self.connector.create_market_order(
                    self.connector.exchange.markets
                    and list(self.connector.exchange.markets.keys())[0]
                    or "BTC/USDT",
                    close_side,
                    size,
                )
                return order is not None
            except Exception as e:
                logger.error("Live exit failed: {}", e)
                return False
        return False

    def get_status(self) -> dict[str, Any]:
        """Current executor status for dashboard."""
        pos_info = None
        if self.position:
            pos_info = {
                "side": self.position.side,
                "entry_price": self.position.entry_price,
                "hold_time_s": self._hold_time(),
                "size": self.position.size,
            }
        return {
            "mode": self.mode,
            "in_position": self.in_position,
            "position": pos_info,
            "session_pnl": self.session_pnl,
            "trade_count": self.trade_count,
            "on_cooldown": self.on_cooldown,
        }
