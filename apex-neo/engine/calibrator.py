"""
L7: Auto-Calibration — Kalman tracker, Kelly sizer, EMA recalibrator.

Dynamically adjusts system parameters based on recent performance:
- Kalman filter tracks true signal-to-noise ratio
- Kelly criterion sizes positions optimally
- EMA recalibrator adjusts thresholds based on rolling metrics
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class CalibrationState:
    kalman_gain: float = 0.5
    kalman_estimate: float = 0.0
    kalman_error: float = 1.0
    kelly_fraction: float = 0.02
    ema_volatility: float = 0.01
    ema_win_rate: float = 0.5
    ema_avg_win: float = 0.001
    ema_avg_loss: float = 0.001
    trade_count: int = 0
    confidence_scale: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kalman_gain": self.kalman_gain,
            "kalman_estimate": self.kalman_estimate,
            "kalman_error": self.kalman_error,
            "kelly_fraction": self.kelly_fraction,
            "ema_volatility": self.ema_volatility,
            "ema_win_rate": self.ema_win_rate,
            "ema_avg_win": self.ema_avg_win,
            "ema_avg_loss": self.ema_avg_loss,
            "trade_count": self.trade_count,
            "confidence_scale": self.confidence_scale,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CalibrationState:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Calibrator:
    """L7 signal layer: adaptive parameter calibration."""

    def __init__(self, ema_alpha: float = 0.05) -> None:
        self.alpha = ema_alpha
        self.state = CalibrationState()
        self.returns: deque[float] = deque(maxlen=200)
        # Kalman params
        self._process_noise = 0.001
        self._measurement_noise = 0.01

    def load_state(self, data: dict[str, Any]) -> None:
        cal_data = data.get("calibrator", {})
        if cal_data:
            self.state = CalibrationState.from_dict(cal_data)

    def save_state(self) -> dict[str, Any]:
        return {"calibrator": self.state.to_dict()}

    def update_price(self, price: float) -> None:
        """Update Kalman filter with new price observation."""
        # Prediction step
        pred_estimate = self.state.kalman_estimate
        pred_error = self.state.kalman_error + self._process_noise

        # Update step
        gain = pred_error / (pred_error + self._measurement_noise)
        self.state.kalman_estimate = pred_estimate + gain * (price - pred_estimate)
        self.state.kalman_error = (1 - gain) * pred_error
        self.state.kalman_gain = gain

    def update_trade(self, pnl_pct: float) -> None:
        """Update calibration after a trade completes."""
        self.returns.append(pnl_pct)
        self.state.trade_count += 1

        is_win = pnl_pct > 0

        # EMA win rate
        self.state.ema_win_rate += self.alpha * ((1.0 if is_win else 0.0) - self.state.ema_win_rate)

        # EMA average win/loss
        if is_win:
            self.state.ema_avg_win += self.alpha * (pnl_pct - self.state.ema_avg_win)
        else:
            self.state.ema_avg_loss += self.alpha * (abs(pnl_pct) - self.state.ema_avg_loss)

        # EMA volatility
        if len(self.returns) > 5:
            vol = float(np.std(list(self.returns)[-20:]))
            self.state.ema_volatility += self.alpha * (vol - self.state.ema_volatility)

        # Kelly criterion: f* = (p*b - q) / b
        # p = win_rate, q = 1-p, b = avg_win/avg_loss
        p = self.state.ema_win_rate
        q = 1 - p
        b = self.state.ema_avg_win / (self.state.ema_avg_loss + 1e-10)

        kelly = (p * b - q) / (b + 1e-10)
        # Half-Kelly for safety, clamped
        self.state.kelly_fraction = float(np.clip(kelly * 0.5, 0.01, 0.15))

        # Confidence scale: reduce if on losing streak
        recent = list(self.returns)[-10:]
        if len(recent) >= 5:
            recent_wr = sum(1 for r in recent if r > 0) / len(recent)
            self.state.confidence_scale = float(np.clip(0.5 + recent_wr, 0.3, 1.5))

    @property
    def position_size_pct(self) -> float:
        """Recommended position size as fraction of capital."""
        return self.state.kelly_fraction * self.state.confidence_scale

    @property
    def signal_quality(self) -> float:
        """0 to 1 estimate of overall signal quality."""
        if self.state.trade_count < 5:
            return 0.5  # neutral until calibrated
        wr = self.state.ema_win_rate
        edge = wr * self.state.ema_avg_win - (1 - wr) * self.state.ema_avg_loss
        return float(np.clip(0.5 + edge * 10, 0.0, 1.0))
