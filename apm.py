"""Active Position Manager primitives used by v3 services and tests.

Lightweight implementation of:
- VPIN toxicity monitor
- Dynamic OBI trailing stop
- Ghost liquidity reactor
- Alpha decay timer
- ActivePositionManager orchestration
"""
from __future__ import annotations

import math
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

VPIN_TOXIC_THRESHOLD = 0.68
VPIN_CRITICAL_THRESHOLD = 0.86
ALPHA_DECAY_S = 60.0
ALPHA_MIN_MOVE_PCT = 0.35


class ExitReason(str, Enum):
    HARD_STOP = "hard_stop"
    TAKE_PROFIT = "take_profit"
    OBI_TRAIL_STOP = "obi_trail_stop"
    GHOST_LIQUIDITY = "ghost_liquidity"
    ALPHA_DECAY = "alpha_decay"
    VPIN_TOXIC = "vpin_toxic"
    VPIN_CRITICAL = "vpin_critical"
    MACRO_KILL = "macro_kill"
    TIME_LIMIT = "time_limit"
    MANUAL_EXIT = "manual_exit"


@dataclass
class TickData:
    price: float
    volume: float = 0.0
    obi: float = 0.0
    ghost_events: List[Dict[str, Any]] = field(default_factory=list)
    macro_kill: bool = False


@dataclass
class APMDecision:
    action: str
    reason: Optional[ExitReason] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GhostReaction:
    should_exit: bool
    reason: str = ""


@dataclass
class ManagedPosition:
    position_id: str
    symbol: str
    side: str
    entry_price: float
    quantity: float
    opened_at: float
    hard_stop_pct: float
    take_profit_pct: float
    time_limit_s: float
    trail: "DynamicOBITrail"
    ghost: "GhostLiquidityReactor"
    alpha: "AlphaDecayTimer"
    vpin: "VPINComputer"


class VPINComputer:
    def __init__(self, bucket_volume: float = 0.0, max_buckets: int = 50):
        self.bucket_volume = bucket_volume
        self.max_buckets = max_buckets
        self.vpin = 0.0
        self._last_price: Optional[float] = None
        self._cur_buy = 0.0
        self._cur_sell = 0.0
        self._cur_total = 0.0
        self._imbalances: Deque[float] = deque(maxlen=max_buckets)
        self._calibration_samples = 0
        self._calibrated = bucket_volume > 0

    @staticmethod
    def _phi(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @property
    def is_toxic(self) -> bool:
        return self.vpin >= VPIN_TOXIC_THRESHOLD

    @property
    def is_critical(self) -> bool:
        return self.vpin >= VPIN_CRITICAL_THRESHOLD

    def reset(self) -> None:
        self.vpin = 0.0
        self._last_price = None
        self._cur_buy = 0.0
        self._cur_sell = 0.0
        self._cur_total = 0.0
        self._imbalances.clear()

    def ingest_trade(self, price: float, volume: float) -> float:
        if volume <= 0:
            return self.vpin

        if not self._calibrated:
            self._calibration_samples += 1
            if self._calibration_samples >= 120:
                self.bucket_volume = max(1.0, self._calibration_samples * 0.08)
                self._calibrated = True

        if self._last_price is None:
            buy_ratio = 0.5
        elif price > self._last_price:
            buy_ratio = 1.0
        elif price < self._last_price:
            buy_ratio = 0.0
        else:
            buy_ratio = 0.5

        buy_vol = volume * buy_ratio
        sell_vol = volume - buy_vol

        self._cur_buy += buy_vol
        self._cur_sell += sell_vol
        self._cur_total += volume
        self._last_price = price

        bucket = max(self.bucket_volume, 1.0)
        while self._cur_total >= bucket:
            imbalance = abs(self._cur_buy - self._cur_sell) / bucket
            self._imbalances.append(min(1.0, max(0.0, imbalance)))
            self._cur_total -= bucket
            self._cur_buy = 0.0
            self._cur_sell = 0.0

        if self._imbalances:
            self.vpin = sum(self._imbalances) / len(self._imbalances)
        else:
            self.vpin = 0.0
        return self.vpin


class DynamicOBITrail:
    def __init__(self, entry_price: float, side: str, atr: float):
        self.entry_price = float(entry_price)
        self.side = side.upper()
        self.atr = max(atr, entry_price * 0.001)
        self.high_water = entry_price
        self.low_water = entry_price
        self.current_stop = self._initial_stop()

    def _initial_stop(self) -> float:
        if self.side == "LONG":
            return self.entry_price - (1.2 * self.atr)
        return self.entry_price + (1.2 * self.atr)

    def update(self, price: float, obi: float = 0.0) -> tuple[float, str]:
        if self.side == "LONG":
            self.high_water = max(self.high_water, price)
            regime = "tight" if obi < -0.15 else "wide" if obi > 0.15 else "normal"
            mult = 1.3 if regime == "tight" else 1.6 if regime == "wide" else 1.0
            proposed = self.high_water - (self.atr * mult)
            self.current_stop = max(self.current_stop, proposed)
        else:
            self.low_water = min(self.low_water, price)
            regime = "tight" if obi > 0.15 else "wide" if obi < -0.15 else "normal"
            mult = 1.3 if regime == "tight" else 1.6 if regime == "wide" else 1.0
            proposed = self.low_water + (self.atr * mult)
            self.current_stop = min(self.current_stop, proposed)
        return self.current_stop, regime

    def is_triggered(self, price: float) -> bool:
        if self.side == "LONG":
            return price <= self.current_stop
        return price >= self.current_stop


class GhostLiquidityReactor:
    def __init__(self, side: str, min_notional: float = 25_000.0):
        self.side = side.upper()
        self.min_notional = min_notional
        self.events: Deque[Dict[str, Any]] = deque(maxlen=200)

    def ingest_ghost_event(self, event: Dict[str, Any]) -> None:
        e = dict(event)
        e.setdefault("ingested_at", time.monotonic())
        self.events.append(e)

    def evaluate(self, window_s: float = 3.0) -> GhostReaction:
        now = time.monotonic()
        recent = [
            e
            for e in self.events
            if (now - float(e.get("ingested_at", now))) <= window_s
            and float(e.get("notional_usd", 0.0) or 0.0) >= self.min_notional
        ]
        if not recent:
            return GhostReaction(False)

        if self.side == "LONG" and any(str(e.get("side", "")).lower() == "bid" for e in recent):
            return GhostReaction(True, "fake support removed")
        if self.side == "SHORT" and any(str(e.get("side", "")).lower() == "ask" for e in recent):
            return GhostReaction(True, "fake resistance removed")
        return GhostReaction(False)


class AlphaDecayTimer:
    def __init__(self, entry_price: float, side: str, decay_s: float = ALPHA_DECAY_S, min_move_pct: float = ALPHA_MIN_MOVE_PCT):
        self.entry_price = float(entry_price)
        self.side = side.upper()
        self.decay_s = decay_s
        self.min_move_pct = min_move_pct
        self.started_at = time.monotonic()
        self.peak_favorable_pct = 0.0

    def _favorable_move_pct(self, price: float) -> float:
        if self.side == "LONG":
            return ((price - self.entry_price) / self.entry_price) * 100
        return ((self.entry_price - price) / self.entry_price) * 100

    def update(self, price: float) -> tuple[bool, float, float]:
        elapsed = time.monotonic() - self.started_at
        move_pct = self._favorable_move_pct(price)
        self.peak_favorable_pct = max(self.peak_favorable_pct, move_pct)
        decayed = elapsed >= self.decay_s and move_pct < self.min_move_pct
        return decayed, elapsed, move_pct


class ActivePositionManager:
    def __init__(self):
        self.positions: Dict[str, ManagedPosition] = {}
        self.closed: List[Dict[str, Any]] = []

    async def register_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        atr: float,
        hard_stop_pct: float = 2.5,
        take_profit_pct: float = 4.0,
        alpha_decay_s: float = ALPHA_DECAY_S,
        alpha_min_move_pct: float = ALPHA_MIN_MOVE_PCT,
        time_limit_s: float = 3600.0,
        vpin_bucket_vol: float = 25.0,
        ghost_min_notional: float = 25_000.0,
    ) -> str:
        pid = str(uuid.uuid4())
        side_u = side.upper()
        self.positions[pid] = ManagedPosition(
            position_id=pid,
            symbol=symbol,
            side=side_u,
            entry_price=entry_price,
            quantity=quantity,
            opened_at=time.monotonic(),
            hard_stop_pct=hard_stop_pct,
            take_profit_pct=take_profit_pct,
            time_limit_s=time_limit_s,
            trail=DynamicOBITrail(entry_price, side_u, atr=max(atr, entry_price * 0.001)),
            ghost=GhostLiquidityReactor(side_u, min_notional=ghost_min_notional),
            alpha=AlphaDecayTimer(entry_price, side_u, alpha_decay_s, alpha_min_move_pct),
            vpin=VPINComputer(bucket_volume=vpin_bucket_vol),
        )
        return pid

    async def process_tick(self, position_id: str, tick: TickData) -> APMDecision:
        pos = self.positions.get(position_id)
        if pos is None:
            return APMDecision("HOLD", details={"error": "position_not_found"})

        pos.vpin.ingest_trade(tick.price, tick.volume)
        stop, regime = pos.trail.update(tick.price, obi=tick.obi)

        for ev in tick.ghost_events or []:
            pos.ghost.ingest_ghost_event(ev)

        if tick.macro_kill:
            return await self._exit(position_id, ExitReason.MACRO_KILL)

        # hard stop / take profit
        if pos.side == "LONG":
            pnl_pct = ((tick.price - pos.entry_price) / pos.entry_price) * 100
        else:
            pnl_pct = ((pos.entry_price - tick.price) / pos.entry_price) * 100

        if pnl_pct <= -abs(pos.hard_stop_pct):
            return await self._exit(position_id, ExitReason.HARD_STOP, {"pnl_pct": pnl_pct})
        if pnl_pct >= abs(pos.take_profit_pct):
            return await self._exit(position_id, ExitReason.TAKE_PROFIT, {"pnl_pct": pnl_pct})

        if pos.vpin.is_critical:
            return await self._exit(position_id, ExitReason.VPIN_CRITICAL, {"vpin": pos.vpin.vpin})
        if pos.vpin.is_toxic and pnl_pct < 0:
            return await self._exit(position_id, ExitReason.VPIN_TOXIC, {"vpin": pos.vpin.vpin})

        reaction = pos.ghost.evaluate()
        if reaction.should_exit:
            return await self._exit(position_id, ExitReason.GHOST_LIQUIDITY, {"ghost_reason": reaction.reason})

        if pos.trail.is_triggered(tick.price):
            return await self._exit(position_id, ExitReason.OBI_TRAIL_STOP, {"trail_stop": stop, "trail_regime": regime})

        decayed, elapsed, move_pct = pos.alpha.update(tick.price)
        if decayed:
            return await self._exit(position_id, ExitReason.ALPHA_DECAY, {"elapsed": elapsed, "move_pct": move_pct})

        if (time.monotonic() - pos.opened_at) > pos.time_limit_s:
            return await self._exit(position_id, ExitReason.TIME_LIMIT)

        return APMDecision("HOLD", details={"trail_stop": stop, "vpin": pos.vpin.vpin})

    async def force_exit(self, position_id: str, price: float) -> APMDecision:
        if position_id not in self.positions:
            return APMDecision("HOLD", details={"error": "position_not_found"})
        return await self._exit(position_id, ExitReason.MANUAL_EXIT, {"price": price})

    async def _exit(self, position_id: str, reason: ExitReason, details: Optional[Dict[str, Any]] = None) -> APMDecision:
        pos = self.positions.pop(position_id, None)
        if pos is None:
            return APMDecision("HOLD", details={"error": "position_not_found"})
        self.closed.append({
            "position_id": position_id,
            "reason": reason,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "details": details or {},
        })
        return APMDecision("EXIT", reason=reason, details=details or {})

    async def get_active(self) -> Dict[str, Dict[str, Any]]:
        return {
            pid: {
                "symbol": p.symbol,
                "side": p.side,
                "entry_price": p.entry_price,
                "opened_at": p.opened_at,
            }
            for pid, p in self.positions.items()
        }

    async def get_stats(self) -> Dict[str, Any]:
        reasons: Dict[str, int] = {}
        wins = 0
        losses = 0
        for c in self.closed:
            key = c["reason"].value if isinstance(c["reason"], ExitReason) else str(c["reason"])
            reasons[key] = reasons.get(key, 0) + 1
            pnl = float((c.get("details") or {}).get("pnl_pct", 0.0) or 0.0)
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
        return {
            "total_exits": len(self.closed),
            "wins": wins,
            "losses": losses,
            "exit_reasons": reasons,
        }
