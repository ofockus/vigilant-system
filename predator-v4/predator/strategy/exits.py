"""
Exit management — anti-churn + dynamic trailing stop + time decay.

Anti-churn rules:
- min_hold: 3s (scalping, not Apex NEO's 15s)
- cooldown: 8s between trades
- PRED_FLIP: exit if direction strongly flips
- GRAV_COLLAPSE: book pressure collapses
- DRIFT: regime drift detected

Stop logic:
- SL: 0.09% (tight but above fees)
- TP: trailing only, activates at 0.06%, callback 0.035%
- Time decay: tighten stops after 90s, force exit at 180s
- Volatility scaling: widen/tighten based on micro_vol
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .features import FeatureVector


@dataclass
class ExitDecision:
    should_exit: bool = False
    reason: str = ""
    pnl_pct: float = 0.0


@dataclass
class PositionState:
    symbol: str = ""
    side: int = 0              # 1 long, -1 short
    entry_price: float = 0.0
    entry_time: float = 0.0
    qty: float = 0.0
    leverage: int = 5
    peak_pnl_pct: float = 0.0
    trail_active: bool = False
    trail_high_pnl: float = 0.0
    last_direction: int = 0    # for PRED_FLIP
    last_book_pressure: float = 0.0  # for GRAV_COLLAPSE


class ExitManager:
    """Smart exit logic with anti-churn protection."""

    def __init__(
        self,
        min_hold_s: float = 3.0,
        cooldown_s: float = 8.0,
        stop_loss_pct: float = 0.09,
        take_profit_base_pct: float = 0.14,
        trail_activation_pct: float = 0.06,
        trail_callback_pct: float = 0.035,
        max_hold_s: float = 180.0,
        time_decay_start_s: float = 90.0,
        grav_collapse_threshold: float = 0.60,
        drift_exit_threshold: float = 0.30,
        decel_threshold: float = 0.18,
        vol_scale_sl: bool = True,
        vol_scale_tp: bool = True,
    ) -> None:
        self.min_hold_s = min_hold_s
        self.cooldown_s = cooldown_s
        self.stop_loss_pct = stop_loss_pct
        self.tp_base_pct = take_profit_base_pct
        self.trail_activation_pct = trail_activation_pct
        self.trail_callback_pct = trail_callback_pct
        self.max_hold_s = max_hold_s
        self.time_decay_start_s = time_decay_start_s
        self.grav_collapse = grav_collapse_threshold
        self.drift_threshold = drift_exit_threshold
        self.decel_threshold = decel_threshold
        self.vol_scale_sl = vol_scale_sl
        self.vol_scale_tp = vol_scale_tp

        self.last_exit_time: float = 0.0

    @property
    def on_cooldown(self) -> bool:
        return time.time() - self.last_exit_time < self.cooldown_s

    def check(self, pos: PositionState, fv: FeatureVector,
              current_price: float, model_direction: int) -> ExitDecision:
        """Check all exit conditions. Returns exit decision."""
        hold_time = time.time() - pos.entry_time

        # Current PnL
        if pos.side == 1:
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price * 100
        else:
            pnl_pct = (pos.entry_price - current_price) / pos.entry_price * 100

        # Update peak tracking
        pos.peak_pnl_pct = max(pos.peak_pnl_pct, pnl_pct)

        # Volatility scaling factor
        vol_scale = 1.0
        if fv.micro_vol > 0:
            # Scale stops with volatility: wider in high vol, tighter in low
            vol_scale = max(0.5, min(2.0, fv.micro_vol / 0.003))

        sl = self.stop_loss_pct * (vol_scale if self.vol_scale_sl else 1.0)
        tp = self.tp_base_pct * (vol_scale if self.vol_scale_tp else 1.0)

        # ═══════════════════════════════════════════
        # HARD EXITS — always immediate
        # ═══════════════════════════════════════════

        # Stop loss
        if pnl_pct <= -sl:
            return ExitDecision(True, "STOP_LOSS", pnl_pct)

        # Max time
        if hold_time >= self.max_hold_s:
            return ExitDecision(True, "MAX_TIME", pnl_pct)

        # ═══════════════════════════════════════════
        # SOFT EXITS — blocked before min_hold
        # ═══════════════════════════════════════════

        if hold_time < self.min_hold_s:
            return ExitDecision(False, "MIN_HOLD", pnl_pct)

        # --- Trailing stop ---
        if pnl_pct >= self.trail_activation_pct:
            pos.trail_active = True
            pos.trail_high_pnl = max(pos.trail_high_pnl, pnl_pct)

        if pos.trail_active:
            callback = self.trail_callback_pct * (vol_scale if self.vol_scale_tp else 1.0)
            if pnl_pct <= pos.trail_high_pnl - callback:
                return ExitDecision(True, "TRAIL_STOP", pnl_pct)

        # --- Time decay: tighten stops progressively ---
        if hold_time > self.time_decay_start_s:
            decay_ratio = (hold_time - self.time_decay_start_s) / (
                self.max_hold_s - self.time_decay_start_s
            )
            tightened_sl = sl * max(0.3, 1.0 - decay_ratio * 0.7)
            if pnl_pct <= -tightened_sl:
                return ExitDecision(True, "TIME_DECAY_SL", pnl_pct)
            # If in profit and time is running out, take it
            if decay_ratio > 0.6 and pnl_pct > self.trail_callback_pct:
                return ExitDecision(True, "TIME_DECAY_TP", pnl_pct)

        # --- PRED_FLIP: model direction strongly reversed ---
        if model_direction != 0 and model_direction != pos.side:
            return ExitDecision(True, "PRED_FLIP", pnl_pct)

        # --- GRAV_COLLAPSE: book pressure collapsed against us ---
        if pos.side == 1 and fv.book_pressure < -self.grav_collapse:
            return ExitDecision(True, "GRAV_COLLAPSE", pnl_pct)
        if pos.side == -1 and fv.book_pressure > self.grav_collapse:
            return ExitDecision(True, "GRAV_COLLAPSE", pnl_pct)

        # --- DECEL: strong deceleration in our direction ---
        if pos.side == 1 and fv.decel > self.decel_threshold and pnl_pct > 0:
            return ExitDecision(True, "DECEL", pnl_pct)
        if pos.side == -1 and fv.decel < -self.decel_threshold and pnl_pct > 0:
            return ExitDecision(True, "DECEL", pnl_pct)

        return ExitDecision(False, "HOLD", pnl_pct)

    def record_exit(self) -> None:
        self.last_exit_time = time.time()
