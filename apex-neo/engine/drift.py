"""
L6: ADWIN Concept Drift Detection.

ADaptive WINdowing detects distributional shifts in price returns.
When drift is detected, signals that the market regime may be changing.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class DriftSignal:
    drift_detected: bool = False
    drift_magnitude: float = 0.0   # 0 to 1
    window_size: int = 0
    mean_shift: float = 0.0        # direction of shift


class ADWINDetector:
    """
    Simplified ADWIN (ADaptive WINdowing) for concept drift detection.

    Maintains a variable-length window and tests for distributional change
    between sub-windows using Hoeffding bounds.
    """

    def __init__(self, delta: float = 0.002, max_window: int = 500) -> None:
        self.delta = delta
        self.max_window = max_window
        self.window: deque[float] = deque(maxlen=max_window)

    def update(self, value: float) -> DriftSignal:
        self.window.append(value)

        if len(self.window) < 20:
            return DriftSignal(window_size=len(self.window))

        arr = np.array(self.window)
        n = len(arr)
        best_drift = 0.0
        best_shift = 0.0
        detected = False

        # Test split points (sample for efficiency)
        step = max(n // 20, 1)
        for i in range(10, n - 10, step):
            left = arr[:i]
            right = arr[i:]
            n0 = len(left)
            n1 = len(right)

            mean_diff = abs(left.mean() - right.mean())
            harmonic = (1.0 / n0 + 1.0 / n1)

            # Hoeffding bound
            eps = math.sqrt(harmonic * math.log(4.0 / self.delta) / 2.0)

            if mean_diff > eps:
                magnitude = (mean_diff - eps) / (mean_diff + 1e-15)
                if magnitude > best_drift:
                    best_drift = magnitude
                    best_shift = float(right.mean() - left.mean())
                    detected = True

        # Shrink window if drift detected (drop old data)
        if detected and len(self.window) > 30:
            drop = len(self.window) // 3
            for _ in range(drop):
                self.window.popleft()

        return DriftSignal(
            drift_detected=detected,
            drift_magnitude=float(min(best_drift, 1.0)),
            window_size=len(self.window),
            mean_shift=best_shift,
        )


class DriftEngine:
    """L6 signal layer: ADWIN drift detection on price returns."""

    def __init__(self, delta: float = 0.002) -> None:
        self.detector = ADWINDetector(delta=delta)
        self._prev_price: float | None = None

    def update(self, price: float) -> DriftSignal:
        if self._prev_price is None:
            self._prev_price = price
            return DriftSignal()

        # Log return
        ret = math.log(price / self._prev_price) if self._prev_price > 0 else 0.0
        self._prev_price = price

        return self.detector.update(ret)
