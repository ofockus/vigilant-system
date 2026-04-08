"""
L2: Physics Engine — F=ma, velocity, gravity, kinetic energy from order flow.

Models price movement as a physical system:
- Velocity: rate of price change
- Acceleration: rate of velocity change (F=ma where m=volume)
- Gravity: pull toward VWAP (mean-reversion force)
- Kinetic Energy: 0.5 * volume * velocity^2 (momentum energy)

Outputs 4 indicator signals and an aggregate direction.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class PhysicsSignal:
    velocity: float = 0.0
    acceleration: float = 0.0
    gravity: float = 0.0
    kinetic_energy: float = 0.0
    direction: float = 0.0       # aggregate [-1, +1]
    indicators_agree: int = 0    # how many of 4 agree on direction
    decel_magnitude: float = 0.0 # |accel| when decelerating


class PhysicsEngine:
    """L2 signal layer: Newtonian price physics."""

    def __init__(self, window: int = 50) -> None:
        self.window = window
        self.prices: deque[float] = deque(maxlen=window)
        self.volumes: deque[float] = deque(maxlen=window)
        self.velocities: deque[float] = deque(maxlen=window)
        self.vwap_num: float = 0.0
        self.vwap_den: float = 0.0

    def update(self, price: float, volume: float) -> PhysicsSignal:
        self.prices.append(price)
        self.volumes.append(max(volume, 1e-10))

        # Running VWAP
        self.vwap_num += price * volume
        self.vwap_den += volume
        vwap = self.vwap_num / (self.vwap_den + 1e-15)

        if len(self.prices) < 3:
            return PhysicsSignal()

        # Velocity: normalized price change
        v = (self.prices[-1] - self.prices[-2]) / (self.prices[-2] + 1e-15) * 10000
        self.velocities.append(v)

        if len(self.velocities) < 3:
            return PhysicsSignal(velocity=v)

        # Acceleration: F/m = dv/dt, weighted by inverse volume (lighter = more responsive)
        dv = self.velocities[-1] - self.velocities[-2]
        mass = np.mean(list(self.volumes)[-5:])
        avg_mass = np.mean(list(self.volumes)) + 1e-15
        accel = dv * (avg_mass / (mass + 1e-15))

        # Gravity: pull toward VWAP
        deviation = (price - vwap) / (vwap + 1e-15)
        gravity = -deviation * 100  # stronger pull when further from VWAP

        # Kinetic energy: 0.5 * m * v^2
        vol_ratio = self.volumes[-1] / (avg_mass + 1e-15)
        ke = 0.5 * vol_ratio * (self.velocities[-1] ** 2)

        # Direction from each indicator
        signs = [
            1.0 if v > 0 else -1.0,        # velocity direction
            1.0 if accel > 0 else -1.0,     # acceleration direction
            1.0 if gravity > 0 else -1.0,   # gravity direction (toward VWAP)
            1.0 if v > 0 else -1.0,         # KE direction (same as velocity)
        ]

        # Count agreement
        long_count = sum(1 for s in signs if s > 0)
        short_count = 4 - long_count
        agree = max(long_count, short_count)

        # Aggregate direction: weighted blend
        raw = 0.35 * np.tanh(v) + 0.30 * np.tanh(accel) + 0.20 * np.tanh(gravity) + 0.15 * np.sign(v) * min(ke / 10, 1)
        direction = float(np.clip(raw, -1.0, 1.0))

        # Deceleration magnitude: when velocity and acceleration have opposite signs
        is_decel = (v > 0 and accel < 0) or (v < 0 and accel > 0)
        decel_mag = abs(accel) if is_decel else 0.0

        return PhysicsSignal(
            velocity=float(v),
            acceleration=float(accel),
            gravity=float(gravity),
            kinetic_energy=float(ke),
            direction=direction,
            indicators_agree=agree,
            decel_magnitude=float(decel_mag),
        )
