"""
Signal generation — 3/3 confirmation logic + entry filter.

Three independent confirmation groups must agree before entry:
1. Flow confirmation: book_imbalance + flow_delta agree on direction
2. Momentum confirmation: velocity + decel agree (not decelerating against us)
3. ML confirmation: model confidence >= threshold

Plus orderbook quality filter (spread not too wide, sufficient depth).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .features import FeatureVector


@dataclass
class Signal:
    symbol: str = ""
    direction: int = 0         # 1 long, -1 short, 0 no trade
    confidence: float = 0.0
    confirmations: int = 0
    total_checks: int = 3
    flow_ok: bool = False
    momentum_ok: bool = False
    model_ok: bool = False
    book_filter_ok: bool = False
    reason: str = ""


class SignalGenerator:
    """3/3 confirmation entry signal with orderbook filter."""

    def __init__(
        self,
        min_confirmations: int = 3,
        min_model_confidence: float = 0.68,
        min_book_imbalance: float = 0.15,
        min_flow_delta: float = 0.10,
        decel_threshold: float = 0.18,
        ek_rev_threshold: float = 0.25,
        max_spread_pct: float = 0.03,
    ) -> None:
        self.min_conf = min_confirmations
        self.min_model_confidence = min_model_confidence
        self.min_book_imbalance = min_book_imbalance
        self.min_flow_delta = min_flow_delta
        self.decel_threshold = decel_threshold
        self.ek_rev_threshold = ek_rev_threshold
        self.max_spread_pct = max_spread_pct

    def evaluate(self, fv: FeatureVector, model_direction: int,
                 model_confidence: float) -> Signal:
        """Evaluate entry signal from features + model prediction."""
        sig = Signal(symbol=fv.symbol, total_checks=3)

        if model_direction == 0:
            sig.reason = "NO_DIRECTION"
            return sig

        direction = model_direction

        # --- Check 1: Flow confirmation ---
        flow_agrees = False
        if direction == 1:
            flow_agrees = (
                fv.book_imbalance_5 > self.min_book_imbalance
                and fv.flow_delta > self.min_flow_delta
            )
        elif direction == -1:
            flow_agrees = (
                fv.book_imbalance_5 < -self.min_book_imbalance
                and fv.flow_delta < -self.min_flow_delta
            )
        sig.flow_ok = flow_agrees

        # --- Check 2: Momentum confirmation ---
        # Not decelerating against our direction
        decel_against = False
        if direction == 1 and fv.decel > self.decel_threshold:
            decel_against = True  # upward momentum decelerating
        elif direction == -1 and fv.decel < -self.decel_threshold:
            decel_against = True  # downward momentum decelerating

        # EK reversal shouldn't be triggering against us
        ek_against = False
        if direction == 1 and fv.ek_rev > self.ek_rev_threshold:
            ek_against = True
        elif direction == -1 and fv.ek_rev < -self.ek_rev_threshold:
            ek_against = True

        velocity_agrees = (
            (direction == 1 and fv.velocity > 0) or
            (direction == -1 and fv.velocity < 0)
        )

        sig.momentum_ok = velocity_agrees and not decel_against and not ek_against

        # --- Check 3: ML model confidence ---
        sig.model_ok = model_confidence >= self.min_model_confidence

        # --- Book quality filter (not counted as confirmation, but required) ---
        sig.book_filter_ok = fv.spread_pct < self.max_spread_pct and fv.spread_z < 2.0

        # --- Tally ---
        sig.confirmations = sum([sig.flow_ok, sig.momentum_ok, sig.model_ok])
        sig.confidence = model_confidence

        if sig.confirmations >= self.min_conf and sig.book_filter_ok:
            sig.direction = direction
            sig.reason = "ENTRY"
        else:
            fails = []
            if not sig.flow_ok:
                fails.append("FLOW")
            if not sig.momentum_ok:
                fails.append("MOM")
            if not sig.model_ok:
                fails.append(f"ML({model_confidence:.2f})")
            if not sig.book_filter_ok:
                fails.append("SPREAD")
            sig.reason = "REJECT:" + "+".join(fails)

        return sig
