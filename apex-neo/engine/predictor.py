"""
L1: OU Mean-Reversion + Momentum Predictor.

Ornstein-Uhlenbeck process estimates mean-reversion tendency.
Momentum overlay via exponential regression on recent prices.
Outputs a directional signal [-1, +1] and confidence [0, 1].
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass
class PredictorSignal:
    direction: float = 0.0   # -1 (short) to +1 (long)
    confidence: float = 0.0  # 0 to 1
    ou_mu: float = 0.0       # OU estimated mean
    ou_theta: float = 0.0    # OU mean-reversion speed
    momentum: float = 0.0    # momentum slope


class Predictor:
    """L1 signal layer: OU mean-reversion + momentum."""

    def __init__(self, ou_window: int = 100, momentum_window: int = 20) -> None:
        self.ou_window = ou_window
        self.momentum_window = momentum_window
        self.prices: deque[float] = deque(maxlen=ou_window)

    def update(self, price: float) -> PredictorSignal:
        self.prices.append(price)

        if len(self.prices) < max(20, self.momentum_window + 1):
            return PredictorSignal()

        arr = np.array(self.prices)

        # --- OU parameter estimation (discrete approximation) ---
        x = arr[:-1]
        dx = np.diff(arr)
        n = len(dx)

        if n < 10:
            return PredictorSignal()

        x_mean = x.mean()
        dx_mean = dx.mean()

        # Least-squares regression: dx = a + b*x + noise
        sx = np.sum(x - x_mean)
        sxx = np.sum((x - x_mean) ** 2)
        sxdx = np.sum((x - x_mean) * (dx - dx_mean))

        if sxx < 1e-15:
            return PredictorSignal()

        b = sxdx / sxx
        a = dx_mean - b * x_mean

        # OU params: theta = -b, mu = -a/b (if b < 0)
        theta = max(-b, 0.001)
        mu = -a / b if abs(b) > 1e-10 else arr[-1]

        # --- Momentum (exponential weighted slope) ---
        mom_slice = arr[-self.momentum_window:]
        t = np.arange(len(mom_slice), dtype=float)
        weights = np.exp(0.1 * t)
        weights /= weights.sum()

        t_w = np.sum(weights * t)
        p_w = np.sum(weights * mom_slice)
        slope = np.sum(weights * (t - t_w) * (mom_slice - p_w)) / (
            np.sum(weights * (t - t_w) ** 2) + 1e-15
        )

        # Normalize momentum relative to price
        mom_norm = slope / (arr[-1] + 1e-15) * 1000

        # --- Combine signals ---
        # OU deviation: how far from mean (positive = above mean → short bias)
        deviation = (arr[-1] - mu) / (arr.std() + 1e-15)
        ou_signal = -np.tanh(deviation * theta)  # mean-reversion pull

        # Blend: 60% OU + 40% momentum
        raw = 0.6 * ou_signal + 0.4 * np.tanh(mom_norm)
        direction = float(np.clip(raw, -1.0, 1.0))

        # Confidence from agreement between OU and momentum
        agreement = 1.0 - abs(np.sign(ou_signal) - np.sign(mom_norm)) / 2
        vol_ratio = min(arr.std() / (abs(arr[-1]) + 1e-15) * 100, 1.0)
        confidence = float(np.clip(agreement * 0.7 + vol_ratio * 0.3, 0.0, 1.0))

        return PredictorSignal(
            direction=direction,
            confidence=confidence,
            ou_mu=float(mu),
            ou_theta=float(theta),
            momentum=float(mom_norm),
        )
