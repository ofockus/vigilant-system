"""
L3: VPIN Toxicity + Liquidation Cascade Detection.

Volume-synchronized Probability of Informed Trading (VPIN) measures
order flow toxicity. High VPIN → market makers withdrawing → danger.
Liquidation cascade detector watches for rapid consecutive liquidations.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class ToxicitySignal:
    vpin: float = 0.0            # 0 to 1 (1 = maximum toxicity)
    vpin_critical: bool = False  # True when VPIN > threshold
    liq_cascade: bool = False    # True when liquidation cascade detected
    liq_intensity: float = 0.0   # 0 to 1
    safe_to_trade: bool = True


class VPINCalculator:
    """Volume-synchronized probability of informed trading."""

    def __init__(self, n_buckets: int = 50, bucket_volume: Optional[float] = None) -> None:
        self.n_buckets = n_buckets
        self.bucket_volume = bucket_volume  # auto-calibrated if None
        self.buy_volumes: deque[float] = deque(maxlen=n_buckets)
        self.sell_volumes: deque[float] = deque(maxlen=n_buckets)
        self.current_buy: float = 0.0
        self.current_sell: float = 0.0
        self.current_bucket_vol: float = 0.0
        self.total_volume_seen: float = 0.0
        self.tick_count: int = 0

    def _auto_bucket_size(self) -> float:
        """Auto-calibrate bucket size to ~1/500th of total volume seen."""
        if self.total_volume_seen < 100:
            return 1000.0  # default until calibrated
        return self.total_volume_seen / (self.tick_count + 1) * 10

    def update(self, price: float, volume: float, is_buy: bool) -> float:
        """Add a trade and return current VPIN estimate [0, 1]."""
        self.total_volume_seen += volume
        self.tick_count += 1

        if self.bucket_volume is None:
            self.bucket_volume = self._auto_bucket_size()

        if is_buy:
            self.current_buy += volume
        else:
            self.current_sell += volume

        self.current_bucket_vol += volume

        # Fill bucket
        while self.current_bucket_vol >= self.bucket_volume:
            self.buy_volumes.append(self.current_buy)
            self.sell_volumes.append(self.current_sell)
            overflow = self.current_bucket_vol - self.bucket_volume
            ratio = overflow / (self.current_bucket_vol + 1e-15)
            self.current_buy *= ratio
            self.current_sell *= ratio
            self.current_bucket_vol = overflow

        if len(self.buy_volumes) < 5:
            return 0.0

        buys = np.array(self.buy_volumes)
        sells = np.array(self.sell_volumes)
        total = buys + sells + 1e-15
        imbalance = np.abs(buys - sells)
        vpin = float(np.mean(imbalance / total))

        return min(vpin, 1.0)


class LiquidationDetector:
    """Detects liquidation cascades from rapid large trades."""

    def __init__(self, window_s: float = 30.0, threshold: int = 5) -> None:
        self.window_s = window_s
        self.threshold = threshold
        self.events: deque[tuple[float, float]] = deque()  # (timestamp, size)

    def add_event(self, timestamp: float, size: float) -> None:
        self.events.append((timestamp, size))
        self._prune(timestamp)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self.events and self.events[0][0] < cutoff:
            self.events.popleft()

    def check(self, now: float) -> tuple[bool, float]:
        """Returns (cascade_detected, intensity 0-1)."""
        self._prune(now)
        count = len(self.events)
        intensity = min(count / (self.threshold * 2), 1.0)
        return count >= self.threshold, intensity


class ToxicityEngine:
    """L3 signal layer: VPIN + liquidation detection."""

    def __init__(self, n_buckets: int = 50, vpin_critical: float = 0.90) -> None:
        self.vpin_calc = VPINCalculator(n_buckets=n_buckets)
        self.liq_detector = LiquidationDetector()
        self.vpin_critical_threshold = vpin_critical

    def update_trade(self, price: float, volume: float, is_buy: bool, timestamp: float) -> ToxicitySignal:
        vpin = self.vpin_calc.update(price, volume, is_buy)
        vpin_crit = vpin > self.vpin_critical_threshold

        # Large trades might be liquidations (>5x avg volume)
        avg_vol = self.vpin_calc.total_volume_seen / max(self.vpin_calc.tick_count, 1)
        if volume > avg_vol * 5:
            self.liq_detector.add_event(timestamp, volume)

        cascade, intensity = self.liq_detector.check(timestamp)
        safe = not vpin_crit and not cascade

        return ToxicitySignal(
            vpin=vpin,
            vpin_critical=vpin_crit,
            liq_cascade=cascade,
            liq_intensity=intensity,
            safe_to_trade=safe,
        )
