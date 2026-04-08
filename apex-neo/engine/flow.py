"""
L8: Order Flow Imbalance.

Tracks aggressive buys vs sells from the trade stream to detect
directional pressure. Uses volume-weighted imbalance over a rolling window.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class FlowSignal:
    imbalance: float = 0.0      # -1 (sell pressure) to +1 (buy pressure)
    buy_volume: float = 0.0     # total buy volume in window
    sell_volume: float = 0.0    # total sell volume in window
    intensity: float = 0.0      # 0 to 1 (how strong the flow is vs normal)
    delta: float = 0.0          # cumulative volume delta


@dataclass
class TradeEvent:
    timestamp: float
    price: float
    volume: float
    is_buy: bool


class OrderFlowEngine:
    """L8 signal layer: order flow imbalance from trade stream."""

    def __init__(self, window_s: float = 60.0, intensity_lookback: int = 500) -> None:
        self.window_s = window_s
        self.trades: deque[TradeEvent] = deque(maxlen=5000)
        self.cum_delta: float = 0.0
        self.volume_history: deque[float] = deque(maxlen=intensity_lookback)

    def update(self, price: float, volume: float, is_buy: bool, timestamp: float) -> FlowSignal:
        event = TradeEvent(timestamp=timestamp, price=price, volume=volume, is_buy=is_buy)
        self.trades.append(event)

        # Cumulative delta
        if is_buy:
            self.cum_delta += volume
        else:
            self.cum_delta -= volume

        # Track volume for intensity calculation
        self.volume_history.append(volume)

        # Prune old trades outside window
        cutoff = timestamp - self.window_s
        while self.trades and self.trades[0].timestamp < cutoff:
            self.trades.popleft()

        # Calculate window imbalance
        buy_vol = 0.0
        sell_vol = 0.0
        for t in self.trades:
            if t.is_buy:
                buy_vol += t.volume
            else:
                sell_vol += t.volume

        total = buy_vol + sell_vol
        if total < 1e-10:
            return FlowSignal()

        imbalance = (buy_vol - sell_vol) / total

        # Intensity: current volume vs historical average
        if len(self.volume_history) > 20:
            avg_vol = float(np.mean(list(self.volume_history)))
            window_vol_rate = total / self.window_s if self.window_s > 0 else 0
            normal_rate = avg_vol * len(self.volume_history) / (self.window_s * 10)
            intensity = min(window_vol_rate / (normal_rate + 1e-10), 1.0)
        else:
            intensity = 0.5

        return FlowSignal(
            imbalance=float(imbalance),
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            intensity=float(np.clip(intensity, 0.0, 1.0)),
            delta=self.cum_delta,
        )
